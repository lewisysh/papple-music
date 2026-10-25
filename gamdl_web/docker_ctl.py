from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

# GUI-launched servers on macOS often miss the usual Docker install locations.
_EXTRA_PATHS = [
    "/usr/local/bin",
    "/opt/homebrew/bin",
    str(Path.home() / ".orbstack" / "bin"),
    "/Applications/Docker.app/Contents/Resources/bin",
]
_CONTAINER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
ACTIONS = {"start", "stop", "restart"}


def find_docker() -> str | None:
    search_path = os.pathsep.join([os.environ.get("PATH", ""), *_EXTRA_PATHS])
    return shutil.which("docker", path=search_path)


def _check_name(container: str) -> None:
    if not _CONTAINER_RE.match(container):
        raise ValueError(f"잘못된 컨테이너 이름: {container!r}")


async def _run(*args: str, timeout: float = 30) -> tuple[int, str]:
    docker = find_docker()
    if docker is None:
        return 127, "docker not found"
    proc = await asyncio.create_subprocess_exec(
        docker,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "docker command timed out"
    return proc.returncode, out.decode(errors="replace")


async def status(container: str) -> dict[str, Any]:
    _check_name(container)
    result: dict[str, Any] = {
        "available": find_docker() is not None,
        "daemon": False,
        "container": container,
        "exists": False,
        "state": None,
        "message": None,
    }
    if not result["available"]:
        result["message"] = "docker 명령을 찾을 수 없습니다 (OrbStack 또는 Docker Desktop 설치 필요)"
        return result

    code, out = await _run("inspect", "--format", "{{json .State}}", container, timeout=10)
    if code == 0:
        result["daemon"] = True
        result["exists"] = True
        try:
            state = json.loads(out.strip().splitlines()[-1])
        except (ValueError, IndexError):
            state = {}
        result["state"] = state.get("Status")
        result["started_at"] = state.get("StartedAt")
        result["health"] = (state.get("Health") or {}).get("Status")
    elif "no such object" in out.lower() or "no such container" in out.lower():
        result["daemon"] = True
        result["message"] = "컨테이너가 아직 없습니다. 위의 설치 마법사로 설치하세요."
    else:
        result["message"] = out.strip()[-500:] or "docker 데몬에 연결할 수 없습니다"
    return result


async def action(container: str, name: str) -> tuple[bool, str]:
    _check_name(container)
    if name not in ACTIONS:
        raise ValueError(f"지원하지 않는 동작: {name}")
    code, out = await _run(name, container, timeout=90)
    return code == 0, out.strip()


async def logs(container: str, tail: int = 300) -> str:
    _check_name(container)
    code, out = await _run("logs", "--tail", str(max(1, min(tail, 5000))), container)
    return out
