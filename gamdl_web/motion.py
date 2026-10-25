from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

import httpx
import m3u8

from .config import DATA_DIR, SettingsStore
from .search import SearchService

CACHE_DIR = DATA_DIR / "motion"
PREVIEW_MAX_SIDE = 600


class MotionError(Exception):
    pass


async def _variants(master_url: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(master_url)
        response.raise_for_status()
    playlist = m3u8.loads(response.text, uri=master_url)
    variants = []
    for p in playlist.playlists:
        info = p.stream_info
        width, height = info.resolution or (0, 0)
        variants.append({
            "uri": p.absolute_uri,
            "width": width,
            "height": height,
            "bandwidth": info.bandwidth or 0,
            "hevc": (info.codecs or "").startswith(("hvc1", "hev1")),
        })
    return variants


def _pick(variants: list[dict], quality: str) -> dict:
    if quality == "preview":
        # Small H.264 so every browser can play it inline.
        small = [v for v in variants if not v["hevc"] and max(v["width"], v["height"]) <= PREVIEW_MAX_SIDE]
        pool = small or [v for v in variants if not v["hevc"]] or variants
        return max(pool, key=lambda v: (v["width"] * v["height"], v["bandwidth"]))
    return max(variants, key=lambda v: (v["width"] * v["height"], v["bandwidth"]))


async def save(master_url: str, target: Path, quality: str, ffmpeg: str = "ffmpeg") -> Path:
    """Remux one variant of Apple's motion artwork (plain HLS, no DRM) into an mp4."""
    variant = _pick(await _variants(master_url), quality)
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    args = [shutil.which(ffmpeg) or ffmpeg, "-y", "-v", "error", "-i", variant["uri"], "-map", "0:v:0", "-c", "copy"]
    if variant["hevc"]:
        # QuickTime and Finder only play HEVC in mp4 when tagged hvc1.
        args += ["-tag:v", "hvc1"]
    args += ["-movflags", "+faststart", "-f", "mp4", str(part)]
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    if proc.returncode != 0:
        if part.exists():
            part.unlink()
        raise MotionError(err.decode(errors="replace").strip()[-300:] or "ffmpeg failed")
    os.replace(part, target)
    return target


class MotionService:
    """Motion album covers, cached on disk per album and quality."""

    def __init__(self, store: SettingsStore, search: SearchService) -> None:
        self.store = store
        self.search = search
        self._locks: dict[str, asyncio.Lock] = {}

    async def master(self, album_id: str) -> str | None:
        return await self.search.motion_master(album_id)

    async def cached(self, album_id: str, quality: str) -> Path | None:
        target = CACHE_DIR / f"{album_id}-{quality}.mp4"
        lock = self._locks.setdefault(target.name, asyncio.Lock())
        async with lock:
            if target.exists():
                return target
            master = await self.master(album_id)
            if not master:
                return None
            return await save(master, target, quality, self.store.get().ffmpeg_path)
