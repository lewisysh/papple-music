"""Guided wrapper-v2 install, driven from the Wrapper tab.

Replaces scripts/setup-wrapper.sh for people who only have the app: it finds and
verifies the user's Apple Music APK, downloads the wrapper-v2 source, stages
the Apple and Android libraries (hash-checked against wrapper-v2's
LIBS_VERSION.json), builds the image with Docker and starts the container.
The APK is never shipped with Papple Music; the user provides their own.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import platform
import re
import shutil
import zipfile
from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import structlog

from . import docker_ctl
from .config import DATA_DIR, SettingsStore

logger = structlog.get_logger("gamdl_web.wrapper_setup")

SETUP_DIR = DATA_DIR / "wrapper-setup"
APK_DIR = DATA_DIR / "apk"
WRAPPER_DATA = DATA_DIR / "wrapper"
SOURCE_ZIP = "https://codeload.github.com/glomatico/wrapper-v2/zip/refs/heads/main"
LIBS_VERSION_URL = "https://raw.githubusercontent.com/glomatico/wrapper-v2/main/LIBS_VERSION.json"
IMAGE = os.environ.get("GAMDL_WEB_WRAPPER_IMAGE", "wrapper-v2:latest")
SENTINEL = "libandroidappmusic.so"
APK_SUFFIXES = {".apk", ".apkm", ".xapk"}
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
STEPS = ["source", "libs", "system", "build", "start", "health"]
SEARCH_DIRS = [APK_DIR, Path.home() / "Downloads", Path.home() / "Desktop"]


class SetupError(Exception):
    pass


def host_arch() -> tuple[str, str]:
    """(wrapper TARGET_ARCH, docker platform) for this machine."""
    if platform.machine().lower() in {"arm64", "aarch64"}:
        return "arm64-v8a", "linux/arm64"
    return "x86_64", "linux/amd64"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _lib_dir(zf: zipfile.ZipFile, arch: str) -> str | None:
    names = set(zf.namelist())
    candidates = ["lib/arm64-v8a", "lib/arm64"] if arch == "arm64-v8a" else ["lib/x86_64", "lib/x86"]
    return next((d for d in candidates if f"{d}/{SENTINEL}" in names), None)


def _open_libs(apk: Path, arch: str) -> tuple[zipfile.ZipFile, str]:
    """The zip (the APK itself or a split inside an .apkm bundle) holding this arch's libs."""
    outer = zipfile.ZipFile(apk)
    lib_dir = _lib_dir(outer, arch)
    if lib_dir:
        return outer, lib_dir
    for name in outer.namelist():
        if name.endswith(".apk"):
            inner = zipfile.ZipFile(io.BytesIO(outer.read(name)))
            lib_dir = _lib_dir(inner, arch)
            if lib_dir:
                outer.close()
                return inner, lib_dir
            inner.close()
    outer.close()
    raise SetupError(f"이 APK에는 {arch}용 Apple Music 라이브러리가 없습니다")


class WrapperSetup:
    def __init__(self, store: SettingsStore) -> None:
        self.store = store
        self.task: asyncio.Task | None = None
        self.proc: asyncio.subprocess.Process | None = None
        self.state = "idle"  # idle | running | done | error | canceled
        self.step: str | None = None
        self.done_steps: list[str] = []
        self.progress = 0.0
        self.error: str | None = None
        self.log: deque[str] = deque(maxlen=400)
        self._libs: dict | None = None
        self._apk_cache: dict[tuple[str, float], dict] = {}

    # ---- checks -------------------------------------------------------------

    async def libs_version(self) -> dict:
        if self._libs is None:
            cached = SETUP_DIR / "LIBS_VERSION.json"
            try:
                async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                    response = await client.get(LIBS_VERSION_URL)
                    response.raise_for_status()
                SETUP_DIR.mkdir(parents=True, exist_ok=True)
                cached.write_bytes(response.content)
            except httpx.HTTPError:
                if not cached.is_file():
                    raise SetupError("wrapper-v2 정보를 받지 못했습니다. 인터넷 연결을 확인하세요.") from None
            self._libs = json.loads(cached.read_text())
        return self._libs

    async def check_apk(self, path: Path) -> dict:
        """Quick check: the arch's main Apple library matches the pinned hash."""
        arch, _ = host_arch()
        key = (str(path), path.stat().st_mtime)
        if key in self._apk_cache:
            return self._apk_cache[key]
        expected = (await self.libs_version())["libs"][arch].get(SENTINEL)
        info = {"path": str(path), "name": path.name, "ok": False, "message": None}

        def check() -> None:
            try:
                zf, lib_dir = _open_libs(path, arch)
                with zf:
                    actual = _sha256(zf.read(f"{lib_dir}/{SENTINEL}"))
                if actual == expected:
                    info["ok"] = True
                else:
                    info["message"] = "버전이 다른 APK입니다 (3.6.0-beta 1109가 필요해요)"
            except (zipfile.BadZipFile, SetupError, KeyError) as e:
                info["message"] = str(e) if isinstance(e, SetupError) else "APK 파일을 읽을 수 없습니다"

        await asyncio.to_thread(check)
        self._apk_cache[key] = info
        return info

    async def find_apk(self) -> dict | None:
        """Newest matching APK in the app folder, Downloads or Desktop."""
        candidates: list[Path] = []
        for folder in SEARCH_DIRS:
            try:
                candidates += [
                    p for p in folder.iterdir()
                    if p.suffix.lower() in APK_SUFFIXES and p.is_file() and p.stat().st_size > 20_000_000
                ]
            except OSError:
                continue
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        mismatch = None
        for path in candidates[:12]:
            info = await self.check_apk(path)
            if info["ok"]:
                return info
            if mismatch is None and "music" in path.name.lower():
                mismatch = info
        return mismatch

    async def save_apk(self, name: str, chunks) -> dict:
        safe = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(name).name) or "AppleMusic.apk"
        if Path(safe).suffix.lower() not in APK_SUFFIXES:
            raise SetupError("APK(.apk / .apkm) 파일만 올릴 수 있습니다")
        APK_DIR.mkdir(parents=True, exist_ok=True)
        target = APK_DIR / safe
        size = 0
        with target.open("wb") as f:
            async for chunk in chunks:
                size += len(chunk)
                if size > 1_000_000_000:
                    f.close()
                    target.unlink(missing_ok=True)
                    raise SetupError("파일이 너무 큽니다")
                f.write(chunk)
        return await self.check_apk(target)

    async def status(self) -> dict[str, Any]:
        settings = self.store.get()
        docker = await docker_ctl.status(settings.wrapper_container)
        apk = None
        error = None
        if self.state != "running":
            try:
                apk = await self.find_apk()
            except SetupError as e:
                error = str(e)
        arch, _ = host_arch()
        return {
            "arch": arch,
            "docker": {"installed": docker["available"], "running": docker["daemon"]},
            "installed": docker["exists"],
            "apk": apk,
            "apk_error": error,
            "state": self.state,
            "step": self.step,
            "done_steps": self.done_steps,
            "steps": STEPS,
            "progress": round(self.progress, 3),
            "error": self.error,
            "log": list(self.log)[-200:],
        }

    # ---- install ------------------------------------------------------------

    def start(self) -> None:
        if self.task and not self.task.done():
            raise SetupError("이미 설치 중입니다")
        self.state, self.step, self.error, self.progress = "running", None, None, 0.0
        self.done_steps = []
        self.log.clear()
        self.task = asyncio.create_task(self._install())

    async def cancel(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()
            if self.proc and self.proc.returncode is None:
                self.proc.kill()

    def _say(self, line: str) -> None:
        self.log.append(ANSI_RE.sub("", line).rstrip())

    def _begin(self, step: str) -> None:
        if self.step:
            self.done_steps.append(self.step)
        self.step = step
        self.progress = len(self.done_steps) / len(STEPS)

    async def _install(self) -> None:
        settings = self.store.get()
        arch, docker_platform = host_arch()
        src = SETUP_DIR / "src"
        try:
            docker = await docker_ctl.status(settings.wrapper_container)
            if not docker["available"] or not docker["daemon"]:
                raise SetupError("Docker가 실행 중이 아닙니다. OrbStack 또는 Docker Desktop을 켜세요.")
            if docker["exists"]:
                raise SetupError(f"'{settings.wrapper_container}' 컨테이너가 이미 있습니다. Docker 메뉴에서 시작하세요.")
            apk = await self.find_apk()
            if not apk or not apk["ok"]:
                raise SetupError("확인된 Apple Music APK가 없습니다")
            libs = await self.libs_version()

            self._begin("source")
            await self._download_source(src)

            self._begin("libs")
            await asyncio.to_thread(self._stage_apple_libs, Path(apk["path"]), arch, libs, src)

            self._begin("system")
            await asyncio.to_thread(self._stage_system, arch, libs, src)

            self._begin("build")
            await self._build(src, arch, docker_platform)

            self._begin("start")
            await self._run_container(settings)

            self._begin("health")
            await self._wait_healthy(settings.wrapper_url)

            self.done_steps.append("health")
            self.step, self.progress, self.state = None, 1.0, "done"
            self.store.update({"use_wrapper": True})
            shutil.rmtree(src, ignore_errors=True)
            self._say("완료! 이제 Apple ID로 로그인하세요.")
        except asyncio.CancelledError:
            self.state = "canceled"
            self._say("설치를 취소했습니다.")
        except Exception as e:  # report every failure to the wizard
            self.state = "error"
            self.error = str(e) or type(e).__name__
            self._say(f"오류: {self.error}")
            logger.warning("wrapper setup failed", error=self.error)
        finally:
            self.proc = None

    async def _download_source(self, src: Path) -> None:
        self._say("wrapper-v2 소스를 받는 중…")
        SETUP_DIR.mkdir(parents=True, exist_ok=True)
        archive = SETUP_DIR / "wrapper-v2.zip"
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=15), follow_redirects=True) as client:
            async with client.stream("GET", SOURCE_ZIP) as response:
                response.raise_for_status()
                with archive.open("wb") as f:
                    async for chunk in response.aiter_bytes(1 << 20):
                        f.write(chunk)

        def unpack() -> None:
            shutil.rmtree(src, ignore_errors=True)
            with zipfile.ZipFile(archive) as zf:
                root = zf.namelist()[0].split("/")[0]
                for member in zf.infolist():
                    rel = member.filename[len(root) + 1:]
                    if not rel or member.is_dir():
                        continue
                    target = src / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as source, target.open("wb") as out:
                        shutil.copyfileobj(source, out)
                    mode = (member.external_attr >> 16) & 0o777
                    if mode:
                        target.chmod(mode)
            archive.unlink(missing_ok=True)

        await asyncio.to_thread(unpack)
        self._say("소스 준비 완료")

    def _stage_apple_libs(self, apk: Path, arch: str, libs: dict, src: Path) -> None:
        self._say(f"APK에서 {arch} 라이브러리를 꺼내는 중…")
        out = src / "rootfs/system/lib64"
        out.mkdir(parents=True, exist_ok=True)
        zf, lib_dir = _open_libs(apk, arch)
        with zf:
            for name, expected in libs["libs"][arch].items():
                try:
                    data = zf.read(f"{lib_dir}/{name}")
                except KeyError:
                    raise SetupError(f"APK에 {name}이(가) 없습니다") from None
                if _sha256(data) != expected:
                    raise SetupError(f"{name} 해시가 맞지 않습니다 (APK 버전을 확인하세요)")
                (out / name).write_bytes(data)
        self._say(f"Apple 라이브러리 {len(libs['libs'][arch])}개 확인")

    def _stage_system(self, arch: str, libs: dict, src: Path) -> None:
        self._say("Android 시스템 파일을 준비하는 중…")
        vendor = src / "vendor/android-system" / arch
        files = {k: v for k, v in libs["android_system"][arch].items() if not k.startswith("$")}
        for rel, expected in files.items():
            source = vendor / rel
            if not source.is_file():
                raise SetupError(f"wrapper-v2 소스에 {rel}이(가) 없습니다")
            data = source.read_bytes()
            if _sha256(data) != expected:
                raise SetupError(f"{rel} 해시가 맞지 않습니다")
            target = src / "rootfs/system" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o755 if rel.startswith("bin/") else 0o644)
        self._say(f"시스템 파일 {len(files)}개 확인")

    async def _build(self, src: Path, arch: str, docker_platform: str) -> None:
        self._say("Docker 이미지를 빌드하는 중… (처음엔 10~15분 걸려요)")
        docker = docker_ctl.find_docker()
        env = {**os.environ, "DOCKER_BUILDKIT": "1", "PATH": os.pathsep.join([str(Path(docker).parent), os.environ.get("PATH", "")])}
        self.proc = await asyncio.create_subprocess_exec(
            docker, "build", "--progress=plain",
            "--build-arg", f"TARGET_ARCH={arch}",
            "--build-arg", f"RUNTIME_PLATFORM={docker_platform}",
            "-t", IMAGE, str(src),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=env,
        )
        step_re = re.compile(r"\[(?:build|stage-\d+|[\w-]+)\s+(\d+)/(\d+)\]")
        base = len(self.done_steps) / len(STEPS)
        span = 1 / len(STEPS)
        assert self.proc.stdout is not None
        async for raw in self.proc.stdout:
            line = raw.decode(errors="replace").rstrip()
            if line:
                self._say(line[-300:])
            m = step_re.search(line)
            if m:
                done, total = int(m[1]), int(m[2])
                self.progress = max(self.progress, base + span * min(0.99, done / max(total, 1)))
        if await self.proc.wait() != 0:
            raise SetupError("Docker 이미지 빌드에 실패했습니다. 아래 로그를 확인하세요.")

    async def _run_container(self, settings) -> None:
        self._say("컨테이너를 시작하는 중…")
        WRAPPER_DATA.mkdir(parents=True, exist_ok=True)
        http_port = urlsplit(settings.wrapper_url).port or 80
        args = [
            "run", "-d", "--name", settings.wrapper_container, "--restart", "unless-stopped",
            "--cap-add", "SYS_ADMIN", "--cap-add", "SYS_CHROOT", "--cap-add", "SYS_PTRACE",
            "--security-opt", "apparmor:unconfined",
            "-p", f"127.0.0.1:{http_port}:80",
            "-p", f"127.0.0.1:{settings.wrapper_decrypt_port}:10020",
            "-v", f"{WRAPPER_DATA}:/app/rootfs/data/data/com.apple.android.music/files",
            IMAGE,
        ]
        code, out = await docker_ctl._run(*args, timeout=120)
        if code != 0:
            raise SetupError(f"컨테이너를 시작하지 못했습니다: {out.strip()[-300:]}")

    async def _wait_healthy(self, wrapper_url: str) -> None:
        self._say("wrapper 응답을 기다리는 중…")
        async with httpx.AsyncClient(timeout=3) as client:
            for _ in range(90):
                try:
                    if (await client.get(f"{wrapper_url}/health")).is_success:
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(1)
        raise SetupError("wrapper가 응답하지 않습니다. Docker 로그를 확인하세요.")
