"""Per-track download progress, reported from inside gamdl's download steps.

jobs.py sets `reporter` around each track's download; the hooks in runner.py
call report() at every stage. Downloads run in a yt-dlp child process, so byte
progress comes from watching the files it writes against the stream's size.
"""

from __future__ import annotations

import asyncio
import re
from contextvars import ContextVar
from pathlib import Path
from typing import Callable

import httpx

Reporter = Callable[[str, int | None, int | None], None]
reporter: ContextVar[Reporter | None] = ContextVar("download_progress", default=None)

BYTERANGE_RE = re.compile(r"BYTERANGE[:=]\"?(\d+)(?:@(\d+))?")


def report(stage: str, done: int | None = None, total: int | None = None) -> None:
    callback = reporter.get()
    if callback is not None:
        callback(stage, done, total)


async def stream_size(url: str) -> int | None:
    """Total bytes of an Apple HLS stream (byte-range playlists) or a plain file."""
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            if url.split("?")[0].endswith(".m3u8"):
                text = (await client.get(url)).text
                ranges = [(int(n), int(o or 0)) for n, o in BYTERANGE_RE.findall(text)]
                return max((o + n for n, o in ranges), default=None) or None
            response = await client.head(url)
            return int(response.headers.get("content-length") or 0) or None
    except (httpx.HTTPError, ValueError):
        return None


def written(path: str) -> int:
    """Bytes yt-dlp has written so far: the file, its .part and fragment files."""
    target = Path(path)
    try:
        return sum(p.stat().st_size for p in target.parent.iterdir() if p.name.startswith(target.name))
    except OSError:
        return 0


async def watch(path: str, total: int | None, stage: str = "download") -> None:
    while True:
        report(stage, written(path), total)
        await asyncio.sleep(0.4)
