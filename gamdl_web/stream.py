from __future__ import annotations

import asyncio
import os
import shutil
import time
from collections import defaultdict
from pathlib import Path

import structlog

from . import convert
from .config import DATA_DIR, SettingsStore
from .prompts import WebPrompts
from .runner import Session, create_session

logger = structlog.get_logger("gamdl_web.stream")

CACHE_DIR = DATA_DIR / "stream"
CACHE_LIMIT = 200
VIDEO_CACHE_LIMIT = 20
SESSION_TTL = 20 * 60

# Browsers cannot play Apple's encrypted streams, so playback downloads the song
# with gamdl as AAC (which every browser decodes) into a small cache first.
STREAM_SETTINGS = {
    "song_codec_priority": ["aac-web", "aac"],
    "song_variant": "",
    "synced_lyrics_only": False,
    "no_synced_lyrics": True,
    "save_cover": False,
    "save_playlist": False,
    "use_playlist_track_path": False,
    "overwrite": False,
    "cover_size": 600,
    "cover_format": "jpg",
    "output_format": "original",
    "album_folder_template": "",
    "compilation_folder_template": "",
    "no_album_folder_template": "",
    "single_disc_file_template": "{title_id}",
    "multi_disc_file_template": "{title_id}",
    "no_album_file_template": "{title_id}",
}


# Lossless streams are fetched as ALAC through the wrapper and served as FLAC,
# which Chrome and Firefox decode (they cannot play ALAC).
QUALITY_SETTINGS = {
    "aac": {"song_codec_priority": ["aac-web", "aac"]},
    "lossless": {"song_codec_priority": ["alac", "aac"], "use_wrapper": True},
    # Music videos: H.264 so every browser can decode them, then cut into HLS.
    "video": {
        "music_video_codec_priority": ["h264"],
        "music_video_resolution": "1080p",
        "music_video_remux_format": "mp4",
    },
}


class StreamError(Exception):
    pass


class StreamService:
    def __init__(self, store: SettingsStore) -> None:
        self.store = store
        self._sessions: dict[str, tuple[Session, float]] = {}
        # One download at a time per quality, so a music video doesn't hold up songs.
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._pending: dict[str, asyncio.Task] = {}

    def cached(self, song_id: str, quality: str) -> Path | None:
        folder = CACHE_DIR / quality
        if quality == "video":
            playlist = folder / song_id / "index.m3u8"
            return playlist if playlist.exists() else None
        for ext in (".flac", ".m4a"):
            path = folder / f"{song_id}{ext}"
            if path.exists():
                return path
        return None

    async def _get_session(self, quality: str) -> Session:
        session, created = self._sessions.get(quality, (None, 0.0))
        if session and time.time() - created < SESSION_TTL:
            return session
        if session:
            await session.close()
        folder = CACHE_DIR / quality
        settings = self.store.get().merged({
            **STREAM_SETTINGS,
            **QUALITY_SETTINGS[quality],
            "output_path": str(folder),
            "temp_path": str(CACHE_DIR / "tmp"),
        })
        session = await create_session(settings, WebPrompts(None, "stream"))
        self._sessions[quality] = (session, time.time())
        return session

    async def _drop_session(self, quality: str) -> None:
        session, _ = self._sessions.pop(quality, (None, 0.0))
        if session:
            await session.close()

    async def _download(self, song_id: str, quality: str) -> Path:
        video = quality == "video"
        async with self._locks[quality]:
            if path := self.cached(song_id, quality):
                return path
            target = CACHE_DIR / quality / f"{song_id}.{'mp4' if video else 'm4a'}"
            for attempt in range(2):
                session = await self._get_session(quality)
                kind = "music-video" if video else "song"
                url = f"https://music.apple.com/{session.apple_music_api.storefront}/{kind}/{song_id}"
                try:
                    async for item in session.downloader.get_download_item_from_url(url):
                        if item.media.partial and not item.media.error:
                            continue
                        await session.downloader.download(item)
                        if item.final_path and Path(item.final_path) != target:
                            os.replace(item.final_path, target)
                    break
                except Exception as e:
                    # A stale token is the usual cause; retry once with a new session.
                    await self._drop_session(quality)
                    if attempt:
                        raise StreamError(str(e) or type(e).__name__) from e
            if not target.exists():
                raise StreamError("재생할 수 있는 음원을 찾지 못했습니다")
            if video:
                target = await self._to_hls(target)
            elif quality == "lossless":
                # ALAC becomes FLAC; a song without ALAC stays the AAC it fell back to.
                flac, _ = await convert.convert(str(target), "flac")
                if flac:
                    target = Path(flac)
        self._trim(quality)
        return target

    async def _to_hls(self, source: Path) -> Path:
        """Repackage a downloaded video as HLS (no re-encode) for the player."""
        folder = source.with_suffix("")
        part = folder.with_name(folder.name + ".part")
        shutil.rmtree(part, ignore_errors=True)
        part.mkdir(parents=True)
        ffmpeg = shutil.which(self.store.get().ffmpeg_path) or "ffmpeg"
        proc = await asyncio.create_subprocess_exec(
            ffmpeg, "-y", "-v", "error", "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
            "-f", "hls", "-hls_time", "6", "-hls_playlist_type", "vod",
            "-hls_segment_type", "fmp4", "-hls_fmp4_init_filename", "init.mp4",
            "-hls_segment_filename", str(part / "seg%04d.m4s"), str(part / "index.m3u8"),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            shutil.rmtree(part, ignore_errors=True)
            raise StreamError(err.decode(errors="replace").strip()[-300:] or "ffmpeg failed")
        shutil.rmtree(folder, ignore_errors=True)
        os.replace(part, folder)
        source.unlink(missing_ok=True)
        return folder / "index.m3u8"

    def _trim(self, quality: str) -> None:
        if quality == "video":
            folders = sorted(
                (p for p in (CACHE_DIR / quality).iterdir() if p.is_dir() and not p.name.endswith(".part")),
                key=lambda p: p.stat().st_mtime, reverse=True,
            )
            for old in folders[VIDEO_CACHE_LIMIT:]:
                shutil.rmtree(old, ignore_errors=True)
            return
        files = sorted((CACHE_DIR / quality).glob("*.*"), key=lambda p: p.stat().st_atime, reverse=True)
        for old in files[CACHE_LIMIT:]:
            old.unlink(missing_ok=True)

    def _task(self, song_id: str, quality: str) -> asyncio.Task:
        key = f"{quality}:{song_id}"
        task = self._pending.get(key)
        if task is None:
            task = asyncio.create_task(self._download(song_id, quality))
            self._pending[key] = task
            task.add_done_callback(lambda t: (self._pending.pop(key, None), t.cancelled() or t.exception()))
        return task

    async def get(self, song_id: str, quality: str = "aac") -> Path:
        if path := self.cached(song_id, quality):
            os.utime(path)
            return path
        return await asyncio.shield(self._task(song_id, quality))

    def prefetch(self, song_id: str, quality: str = "aac") -> None:
        if not self.cached(song_id, quality):
            self._task(song_id, quality)

    async def close(self) -> None:
        for quality in list(self._sessions):
            await self._drop_session(quality)
