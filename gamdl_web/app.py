from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import secrets
import sys
import time
from contextlib import asynccontextmanager
from dataclasses import fields
from http.cookiejar import LoadError, MozillaCookieJar
from pathlib import Path
from typing import Any
from urllib.parse import unquote, quote, urlsplit

import httpx
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from gamdl import __version__ as gamdl_version
from gamdl.api.constants import APPLE_MUSIC_COOKIE_DOMAIN
from gamdl.downloader.enums import DownloadMode, RemuxFormatMusicVideo
from gamdl.interface import (
    AppleMusicInterface,
    ArtistMediaType,
    CoverFormat,
    DrmBackend,
    MediaTags,
    MusicVideoCodec,
    MusicVideoResolution,
    SongCodec,
    SyncedLyricsFormat,
    UploadedVideoQuality,
)
from pydantic import BaseModel, ValidationError

from . import docker_ctl, wrapper
from .config import DATA_DIR, JOB_OVERRIDE_FIELDS, LOG_LEVELS, MP3_BITRATES, OUTPUT_FORMATS, Settings, SettingsStore
from . import convert
from .convert import EXTRA_TAGS
from .formats import FormatService
from .motion import MotionError, MotionService
from .stream import CACHE_DIR as STREAM_CACHE, StreamError, StreamService
from .wrapper_setup import SetupError as WrapperSetupError, WrapperSetup
from .events import EventBus, format_sse
from .jobs import JobManager
from .logs import configure_logging
from .prompts import ARTIST_MEDIA_TYPE_LABELS, PromptBroker
from .runner import SetupError, create_apple_music_api
from .search import ARTIST_VIEWS, SEARCH_TYPES, SearchError, SearchService

STATIC_DIR = Path(__file__).parent / "static"
PASSWORD = os.environ.get("GAMDL_WEB_PASSWORD")


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = SettingsStore()
    bus = EventBus()
    bus.bind_loop(asyncio.get_running_loop())
    broker = PromptBroker(bus)
    manager = JobManager(store, bus, broker)
    configure_logging(store.get().log_level, manager.append_log)
    manager.start()
    app.state.store, app.state.bus = store, bus
    app.state.broker, app.state.manager = broker, manager
    app.state.search = SearchService(store)
    app.state.formats = FormatService(store, app.state.search)
    app.state.motion = MotionService(store, app.state.search)
    manager.motion = app.state.motion
    app.state.stream = StreamService(store)
    app.state.wrapper_setup = WrapperSetup(store)
    warm = asyncio.create_task(app.state.search.warm())
    yield
    warm.cancel()
    await manager.stop()
    await app.state.search.close()
    await app.state.stream.close()


app = FastAPI(title="Papple Music", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# Without a password only loopback names are accepted, so a page on another
# domain that re-points its DNS at 127.0.0.1 (DNS rebinding) cannot reach the API.
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"} | {
    h.strip().lower() for h in os.environ.get("GAMDL_WEB_ALLOWED_HOSTS", "").split(",") if h.strip()
}


def _host_name(host: str) -> str:
    return (urlsplit(f"//{host}").hostname or "").lower()


@app.middleware("http")
async def guard(request: Request, call_next):
    if not PASSWORD and _host_name(request.headers.get("host", "")) not in LOCAL_HOSTS:
        return JSONResponse({"detail": "host not allowed"}, status_code=403)
    if PASSWORD:
        header = request.headers.get("authorization", "")
        ok = False
        if header.startswith("Basic "):
            try:
                _, _, given = base64.b64decode(header[6:]).decode().partition(":")
                ok = secrets.compare_digest(given.encode(), PASSWORD.encode())
            except (ValueError, UnicodeDecodeError):
                ok = False
        if not ok:
            return JSONResponse(
                {"detail": "auth required"},
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Papple Music"'},
            )
    # Block cross-site requests from other pages open in the same browser. Even
    # GETs can start downloads or ffmpeg (stream, motion cover), so reject those
    # when the browser says another site made them.
    if request.url.path.startswith("/api/") and request.headers.get("sec-fetch-site") == "cross-site":
        return JSONResponse({"detail": "cross-site request blocked"}, status_code=403)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "cross-origin request blocked"}, status_code=403)
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        # Revalidate so an updated UI is picked up without a hard refresh.
        response.headers["Cache-Control"] = "no-cache"
    return response


def _state(request: Request):
    return request.app.state


def _error_detail(e: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()
    )


# ---- page & events ---------------------------------------------------------


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/events")
async def events(request: Request):
    state = _state(request)
    queue = state.bus.subscribe()

    async def stream():
        try:
            yield format_sse(
                "snapshot",
                {"jobs": state.manager.snapshot(), "prompts": state.broker.snapshot()},
            )
            while True:
                if await request.is_disconnected():
                    break
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            state.bus.unsubscribe(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


BRAND_DIR = DATA_DIR / "brand"
BRAND_FILE_RE = re.compile(r"[a-z0-9-]+\.(svg|png)")


def _brand_info() -> dict[str, Any]:
    info = {"name": "Papple Music", "tagline": "Enhanced Downloader"}
    try:
        custom = json.loads((BRAND_DIR / "brand.json").read_text())
        info.update({k: str(v) for k, v in custom.items() if k in {"name", "tagline"}})
    except (OSError, ValueError):
        pass
    info["wordmark"] = (BRAND_DIR / "wordmark.svg").is_file()
    return info


@app.get("/brand/{name}")
async def brand_file(name: str):
    """Logo files: a private DATA_DIR/brand folder wins over the bundled ones."""
    if not BRAND_FILE_RE.fullmatch(name):
        raise HTTPException(404, "not found")
    for folder in (BRAND_DIR, STATIC_DIR / "brand"):
        if (folder / name).is_file():
            return FileResponse(folder / name)
    raise HTTPException(404, "not found")


@app.get("/api/meta")
async def meta():
    values = lambda enum: [e.value for e in enum]
    return {
        "gamdl_version": gamdl_version,
        "platform": sys.platform,
        "brand": _brand_info(),
        "data_dir": str(DATA_DIR),
        "options": {
            "song_codec": values(SongCodec),
            "music_video_codec": values(MusicVideoCodec),
            "music_video_resolution": values(MusicVideoResolution),
            "music_video_remux_format": values(RemuxFormatMusicVideo),
            "uploaded_video_quality": values(UploadedVideoQuality),
            "synced_lyrics_format": values(SyncedLyricsFormat),
            "cover_format": values(CoverFormat),
            "download_mode": values(DownloadMode),
            "drm_backend": values(DrmBackend),
            "log_level": LOG_LEVELS,
            "output_format": OUTPUT_FORMATS,
            "mp3_bitrate": MP3_BITRATES,
            "artist_auto_select": [
                {"value": m.value, "label": ARTIST_MEDIA_TYPE_LABELS[m]} for m in ArtistMediaType
            ],
            "tags": ["cover", *(f.name for f in fields(MediaTags)), *EXTRA_TAGS],
        },
    }


# ---- settings & cookies ----------------------------------------------------


@app.get("/api/settings")
async def get_settings(request: Request):
    return _state(request).store.get().model_dump()


def _check_sensitive_settings(current: Settings, changes: dict[str, Any]) -> None:
    """Settings that name programs or files are limited to what they are for, so
    the settings API can't be used to run or overwrite arbitrary files."""

    def changed(key: str) -> str | None:
        value = changes.get(key)
        return value if isinstance(value, str) and value != getattr(current, key) else None

    tools = {"ffmpeg_path": "ffmpeg", "nm3u8dlre_path": "n_m3u8dl-re"}
    for key, expected in tools.items():
        if (value := changed(key)) is not None:
            name = Path(value).name.lower().removesuffix(".exe")
            if not name.startswith(expected):
                raise HTTPException(400, f"{key}: {expected} 실행 파일만 지정할 수 있습니다")
    if (value := changed("cookies_path")) is not None:
        if not Path(value).expanduser().resolve().is_relative_to(DATA_DIR.resolve()):
            raise HTTPException(400, f"cookies_path: {DATA_DIR} 안의 경로만 지정할 수 있습니다")
    for key in ("output_path", "temp_path"):
        if (value := changed(key)) is not None:
            target = Path(value).expanduser()
            if not target.is_absolute() or target.resolve() in {Path("/"), Path.home().resolve()}:
                raise HTTPException(400, f"{key}: 루트나 홈 폴더가 아닌 절대 경로를 지정하세요")


@app.put("/api/settings")
async def put_settings(request: Request, changes: dict[str, Any]):
    state = _state(request)
    _check_sensitive_settings(state.store.get(), changes)
    try:
        settings = state.store.update(changes)
    except ValidationError as e:
        raise HTTPException(400, _error_detail(e))
    configure_logging(settings.log_level, state.manager.append_log)
    return settings.model_dump()


def _cookies_info(path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
    if not info["exists"]:
        return info
    info["modified"] = path.stat().st_mtime
    jar = MozillaCookieJar(str(path))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except (LoadError, OSError) as e:
        info["valid"] = False
        info["error"] = f"Netscape 형식 쿠키 파일이 아닙니다: {e}"
        return info
    token = next(
        (c for c in jar if c.name == "media-user-token" and c.domain == APPLE_MUSIC_COOKIE_DOMAIN),
        None,
    )
    info["valid"] = token is not None
    if token is None:
        info["error"] = "media-user-token 쿠키가 없습니다. music.apple.com에 로그인한 상태로 내보내세요."
    elif token.expires:
        info["expires"] = token.expires
        info["expired"] = token.expires < time.time()
    return info


@app.get("/api/cookies")
async def get_cookies(request: Request):
    return _cookies_info(Path(_state(request).store.get().cookies_path).expanduser())


@app.post("/api/cookies")
async def upload_cookies(request: Request, file: UploadFile = File(...)):
    content = await file.read(1_000_001)
    if len(content) > 1_000_000:
        raise HTTPException(400, "파일이 너무 큽니다")
    path = Path(_state(request).store.get().cookies_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".upload")
    tmp_path.write_bytes(content)
    info = _cookies_info(tmp_path)
    if not info.get("valid"):
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(400, info.get("error", "잘못된 쿠키 파일"))
    tmp_path.replace(path)
    os.chmod(path, 0o600)
    return _cookies_info(path)


class TokenRequest(BaseModel):
    token: str


@app.post("/api/cookies/token")
async def save_token(request: Request, body: TokenRequest):
    """Write a minimal cookies.txt from a pasted media-user-token value."""
    token = body.token.strip().strip('"')
    if len(token) < 20 or any(c.isspace() or c in "\t;" for c in token):
        raise HTTPException(400, "media-user-token 값이 올바르지 않습니다")
    path = Path(_state(request).store.get().cookies_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".upload")
    tmp_path.write_text(
        "# Netscape HTTP Cookie File\n"
        f"{APPLE_MUSIC_COOKIE_DOMAIN}\tTRUE\t/\tTRUE\t0\tmedia-user-token\t{token}\n",
        encoding="utf-8",
    )
    os.chmod(tmp_path, 0o600)
    tmp_path.replace(path)
    return _cookies_info(path)


@app.delete("/api/cookies")
async def delete_cookies(request: Request):
    Path(_state(request).store.get().cookies_path).expanduser().unlink(missing_ok=True)
    return {"ok": True}


class AccountCheck(BaseModel):
    use_wrapper: bool | None = None


@app.post("/api/account/check")
async def check_account(request: Request, body: AccountCheck):
    settings = _state(request).store.get()
    if body.use_wrapper is not None:
        settings = settings.merged({"use_wrapper": body.use_wrapper})
    try:
        api, wrapper_api = await create_apple_music_api(settings)
    except SetupError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"{type(e).__name__}: {e}")
    try:
        return {
            "source": "wrapper" if wrapper_api else "cookies",
            "storefront": api.storefront,
            "active_subscription": api.active_subscription,
            "restricted": bool(api.account_restrictions),
        }
    finally:
        await api.client.aclose()
        if wrapper_api:
            await wrapper_api.client.aclose()


# ---- search ----------------------------------------------------------------


@app.get("/api/search/suggest")
async def search_suggest(request: Request, term: str):
    term = term.strip()
    if not term or len(term) > 100:
        return {"term": term, "terms": [], "items": []}
    try:
        return await _state(request).search.suggest(term)
    except SearchError as e:
        raise HTTPException(502, str(e)) from e


@app.get("/api/search")
async def search(
    request: Request,
    term: str,
    types: str = ",".join(SEARCH_TYPES),
    limit: int = 25,
    offset: int = 0,
    top: bool = False,
):
    term = term.strip()
    if not term or len(term) > 200:
        raise HTTPException(400, "검색어를 입력하세요")
    kinds = [t for t in types.split(",") if t in SEARCH_TYPES]
    if not kinds:
        raise HTTPException(400, "검색할 종류를 고르세요")
    try:
        return await _state(request).search.search(
            term, kinds, max(1, min(limit, 50)), max(0, offset), top
        )
    except SearchError as e:
        raise HTTPException(502, str(e))
    except Exception as e:
        raise HTTPException(502, f"Apple Music 검색에 실패했습니다: {e}")


@app.get("/api/formats")
async def formats(request: Request, type: str, id: str):
    if type not in {"songs", "library-songs", "albums", "playlists"} or not id.replace(".", "").replace("-", "").isalnum():
        raise HTTPException(400, "지원하지 않는 항목입니다")
    try:
        return await _state(request).formats.formats(type, id)
    except Exception as e:
        raise HTTPException(502, f"음질 정보를 가져오지 못했습니다: {e}")


CATALOG_ID_RE = re.compile(r"(?=.*[A-Za-z0-9])[A-Za-z0-9.\-]{1,64}")


@app.get("/api/catalog/{kind}/{item_id}")
async def catalog(request: Request, kind: str, item_id: str):
    search = _state(request).search
    loaders = {
        "albums": search.album,
        "playlists": search.playlist,
        "artists": search.artist,
        "curators": search.curator,
        "library-playlists": search.library_playlist,
    }
    if kind not in loaders or not CATALOG_ID_RE.fullmatch(item_id):
        raise HTTPException(404, "지원하지 않는 항목입니다")
    try:
        return await loaders[kind](item_id)
    except SearchError as e:
        raise HTTPException(502, str(e))


@app.get("/api/browse")
async def browse(request: Request):
    try:
        return await _state(request).search.browse()
    except SearchError as e:
        raise HTTPException(502, str(e))


@app.get("/api/me")
async def me(request: Request):
    search = _state(request).search
    try:
        profile, playlists = await asyncio.gather(search.profile(), search.library_playlists())
    except SearchError as e:
        raise HTTPException(502, str(e))
    return {"profile": profile, "playlists": playlists}


@app.get("/api/motion/albums/{album_id}")
async def motion_cover(request: Request, album_id: str, quality: str = "preview", download: bool = False):
    if quality not in {"preview", "best"} or not album_id.isdigit():
        raise HTTPException(400, "잘못된 요청입니다")
    try:
        path = await _state(request).motion.cached(album_id, quality)
    except (SearchError, MotionError, httpx.HTTPError, ValueError) as e:
        raise HTTPException(502, f"움직이는 커버를 가져오지 못했습니다: {e}") from e
    if path is None:
        raise HTTPException(404, "움직이는 커버가 없는 앨범입니다")
    headers = {"Cache-Control": "max-age=86400"}
    return FileResponse(
        path,
        media_type="video/mp4",
        headers=headers,
        filename=f"{album_id}-motion.mp4" if download else None,
    )


STREAM_QUALITIES = {"aac", "lossless"}


async def _stream_file(request: Request, song_id: str, quality: str) -> tuple[Path, str]:
    if not song_id.isdigit() or quality not in STREAM_QUALITIES:
        raise HTTPException(400, "잘못된 요청입니다")
    try:
        path = await _state(request).stream.get(song_id, quality)
    except StreamError as e:
        raise HTTPException(502, f"재생 준비에 실패했습니다: {e}")
    try:
        info = await convert.probe(str(path), convert._ffprobe_for("ffmpeg"))
    except (convert.ConvertError, OSError, ValueError):
        info = {}
    rate, bits = info.get("sample_rate"), info.get("bits_per_raw_sample") or info.get("bits_per_sample")
    codec = {"flac": "ALAC", "aac": "AAC"}.get(info.get("codec_name"), (info.get("codec_name") or "").upper())
    label = f"{codec} {bits}bit · {int(rate) / 1000:g}kHz" if codec == "ALAC" and rate else f"{codec} 256kbps"
    return path, label


@app.get("/api/stream/{song_id}")
async def stream(request: Request, song_id: str, quality: str = "aac"):
    path, label = await _stream_file(request, song_id, quality)
    return FileResponse(
        path,
        media_type="audio/flac" if path.suffix == ".flac" else "audio/mp4",
        headers={"Cache-Control": "max-age=3600", "X-Stream-Format": quote(label)},
    )


# The player waits here (one cancellable request) instead of pointing <audio> at
# a URL that blocks for the whole download, which ties up browser connections.
@app.get("/api/stream/{song_id}/ready")
async def stream_ready(request: Request, song_id: str, quality: str = "aac"):
    _, label = await _stream_file(request, song_id, quality)
    return {"format": label}


@app.get("/api/video/{video_id}/ready")
async def video_ready(request: Request, video_id: str):
    """Download the full music video (first time only) and return its HLS playlist."""
    if not video_id.isdigit():
        raise HTTPException(400, "잘못된 영상 ID입니다")
    try:
        await _state(request).stream.get(video_id, "video")
    except StreamError as e:
        raise HTTPException(502, f"영상 준비에 실패했습니다: {e}") from e
    return {"hls": f"/api/video/{video_id}/hls/index.m3u8"}


HLS_FILE_RE = re.compile(r"(index\.m3u8|init\.mp4|seg\d{4}\.m4s)")


@app.get("/api/video/{video_id}/hls/{name}")
async def video_hls(video_id: str, name: str):
    if not video_id.isdigit() or not HLS_FILE_RE.fullmatch(name):
        raise HTTPException(404, "not found")
    path = STREAM_CACHE / "video" / video_id / name
    if not path.is_file():
        raise HTTPException(404, "영상이 아직 준비되지 않았습니다")
    media_type = "application/vnd.apple.mpegurl" if name.endswith(".m3u8") else "video/mp4"
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "max-age=3600"})


@app.post("/api/stream/{song_id}/prefetch")
async def stream_prefetch(request: Request, song_id: str, quality: str = "aac"):
    if song_id.isdigit() and quality in STREAM_QUALITIES:
        _state(request).stream.prefetch(song_id, quality)
    return {"ok": True}


@app.get("/api/song/{song_id}")
async def song_info(request: Request, song_id: str):
    if not song_id.isdigit():
        raise HTTPException(400, "잘못된 곡 ID입니다")
    try:
        return await _state(request).search.song(song_id)
    except SearchError as e:
        raise HTTPException(502, str(e))


class PlaylistAdd(BaseModel):
    song_id: str


@app.post("/api/library/playlists/{playlist_id}/tracks")
async def add_to_playlist(request: Request, playlist_id: str, body: PlaylistAdd):
    if not CATALOG_ID_RE.fullmatch(playlist_id) or not body.song_id.isdigit():
        raise HTTPException(400, "잘못된 요청입니다")
    status = await _state(request).search.post(
        f"/v1/me/library/playlists/{playlist_id}/tracks",
        {"data": [{"id": body.song_id, "type": "songs"}]},
    )
    if status >= 300:
        raise HTTPException(502, f"플레이리스트에 추가하지 못했습니다 (HTTP {status})")
    return {"ok": True}


class FolderRequest(BaseModel):
    path: str | None = None


@app.post("/api/open-folder")
async def open_folder(request: Request, body: FolderRequest):
    """Open the download folder (or a folder inside it) in Finder."""
    if sys.platform != "darwin":
        raise HTTPException(400, "macOS에서만 지원합니다")
    output_dir = Path(_state(request).store.get().output_path).expanduser().resolve()
    target = Path(body.path).expanduser().resolve() if body.path else output_dir
    if target.is_file():
        target = target.parent
    if not target.is_relative_to(output_dir):
        raise HTTPException(400, "출력 폴더 밖의 경로입니다")
    if target == output_dir:
        target.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        raise HTTPException(400, "폴더가 없습니다")
    proc = await asyncio.create_subprocess_exec("open", str(target))
    await proc.wait()
    return {"ok": True}


@app.get("/api/catalog/artists/{item_id}/view/{view}")
async def artist_view(request: Request, item_id: str, view: str, offset: int = 0):
    if view not in ARTIST_VIEWS or not CATALOG_ID_RE.fullmatch(item_id):
        raise HTTPException(404, "지원하지 않는 항목입니다")
    try:
        return await _state(request).search.artist_view(item_id, view, max(0, offset))
    except SearchError as e:
        raise HTTPException(502, str(e))


# ---- jobs & prompts --------------------------------------------------------


class JobRequest(BaseModel):
    urls: list[str]
    overrides: dict[str, Any] = {}


@app.get("/api/jobs")
async def list_jobs(request: Request):
    return _state(request).manager.snapshot()


@app.post("/api/jobs")
async def create_job(request: Request, body: JobRequest):
    state = _state(request)
    urls = list(dict.fromkeys(u.strip() for u in body.urls if u.strip()))
    if not urls:
        raise HTTPException(400, "URL을 입력하세요")
    invalid = [u for u in urls if not AppleMusicInterface.get_url_info(u)]
    if invalid:
        raise HTTPException(400, "Apple Music URL이 아닙니다: " + ", ".join(invalid[:3]))
    overrides = {k: v for k, v in body.overrides.items() if k in JOB_OVERRIDE_FIELDS}
    try:
        state.store.get().merged(overrides)
    except ValidationError as e:
        raise HTTPException(400, _error_detail(e))
    return state.manager.submit(urls, overrides).public()


def _job_action(request: Request, job_id: str, fn: str):
    manager = _state(request).manager
    try:
        return getattr(manager, fn)(job_id)
    except KeyError:
        raise HTTPException(404, "작업을 찾을 수 없습니다")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/jobs/clear")
async def clear_jobs(request: Request):
    _state(request).manager.clear_finished()
    return {"ok": True}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(request: Request, job_id: str):
    _job_action(request, job_id, "cancel")
    return {"ok": True}


@app.post("/api/jobs/{job_id}/retry")
async def retry_job(request: Request, job_id: str):
    return _job_action(request, job_id, "retry").public()


@app.delete("/api/jobs/{job_id}")
async def delete_job(request: Request, job_id: str):
    _job_action(request, job_id, "remove")
    return {"ok": True}


class PromptAnswer(BaseModel):
    selected: list[int]


@app.post("/api/prompts/{prompt_id}/answer")
async def answer_prompt(request: Request, prompt_id: str, body: PromptAnswer):
    try:
        _state(request).broker.answer(prompt_id, body.selected)
    except KeyError:
        raise HTTPException(404, "이미 닫힌 선택창입니다")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/prompts/{prompt_id}/cancel")
async def cancel_prompt(request: Request, prompt_id: str):
    try:
        _state(request).broker.cancel(prompt_id)
    except KeyError:
        raise HTTPException(404, "이미 닫힌 선택창입니다")
    return {"ok": True}


# ---- wrapper ---------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str
    password: str


class TwoFactorRequest(BaseModel):
    code: str


def _wrapper_response(result: tuple[int, Any]) -> JSONResponse:
    status, body = result
    return JSONResponse({"status": status, "body": body}, status_code=200 if status < 500 else 502)


@app.get("/api/wrapper/status")
async def wrapper_status(request: Request):
    return await wrapper.get_status(_state(request).store.get())


@app.post("/api/wrapper/login")
async def wrapper_login(request: Request, body: LoginRequest):
    settings = _state(request).store.get()
    return _wrapper_response(await wrapper.login(settings, body.username.strip(), body.password))


@app.post("/api/wrapper/2fa")
async def wrapper_2fa(request: Request, body: TwoFactorRequest):
    settings = _state(request).store.get()
    return _wrapper_response(await wrapper.login_2fa(settings, body.code.strip()))


@app.post("/api/wrapper/logout")
async def wrapper_logout(request: Request):
    return _wrapper_response(await wrapper.logout(_state(request).store.get()))


# ---- wrapper setup wizard ---------------------------------------------------


@app.get("/api/wrapper/setup")
async def wrapper_setup_status(request: Request):
    return await _state(request).wrapper_setup.status()


@app.post("/api/wrapper/setup/apk")
async def wrapper_setup_upload(request: Request):
    """Raw APK upload (the file name comes in X-Filename) into the app's apk folder."""
    name = unquote(request.headers.get("x-filename", "AppleMusic.apk"))
    try:
        return await _state(request).wrapper_setup.save_apk(name, request.stream())
    except WrapperSetupError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/wrapper/setup/start")
async def wrapper_setup_start(request: Request):
    try:
        _state(request).wrapper_setup.start()
    except WrapperSetupError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True}


@app.post("/api/wrapper/setup/cancel")
async def wrapper_setup_cancel(request: Request):
    await _state(request).wrapper_setup.cancel()
    return {"ok": True}


@app.post("/api/wrapper/setup/open-docker")
async def wrapper_setup_open_docker():
    """Launch OrbStack (or Docker Desktop) so its daemon starts."""
    if sys.platform != "darwin":
        raise HTTPException(400, "macOS에서만 지원합니다")
    for app_name in ("OrbStack", "Docker"):
        proc = await asyncio.create_subprocess_exec("open", "-a", app_name)
        if await proc.wait() == 0:
            return {"ok": True, "app": app_name}
    raise HTTPException(404, "OrbStack 또는 Docker Desktop이 설치되어 있지 않습니다")


@app.get("/api/docker")
async def docker_status(request: Request):
    try:
        return await docker_ctl.status(_state(request).store.get().wrapper_container)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/docker/logs")
async def docker_logs(request: Request, tail: int = 300):
    try:
        return {"logs": await docker_ctl.logs(_state(request).store.get().wrapper_container, tail)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/docker/{name}")
async def docker_action(request: Request, name: str):
    try:
        ok, output = await docker_ctl.action(_state(request).store.get().wrapper_container, name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not ok:
        raise HTTPException(400, output or f"docker {name} 실패")
    return {"ok": True, "output": output}


# ---- misc ------------------------------------------------------------------


class RevealRequest(BaseModel):
    path: str


@app.post("/api/reveal")
async def reveal(request: Request, body: RevealRequest):
    if sys.platform != "darwin":
        raise HTTPException(400, "macOS에서만 지원합니다")
    output_dir = Path(_state(request).store.get().output_path).expanduser().resolve()
    target = Path(body.path).expanduser().resolve()
    if not target.is_relative_to(output_dir) or not target.exists():
        raise HTTPException(400, "출력 폴더 밖의 경로이거나 파일이 없습니다")
    proc = await asyncio.create_subprocess_exec("open", "-R", str(target))
    await proc.wait()
    return {"ok": True}


# The UI uses real paths (/search/…, /album/…); serve the page for any of them.
@app.get("/{path:path}")
async def spa(path: str):
    if path.startswith(("api/", "static/")):
        raise HTTPException(404, "not found")
    return FileResponse(STATIC_DIR / "index.html")
