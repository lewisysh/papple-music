from __future__ import annotations

import asyncio
import re
from collections import OrderedDict
from typing import Any

import httpx
import m3u8
import structlog
from gamdl.api.constants import APPLE_MUSIC_AMP_API_URL

from .config import SettingsStore
from .search import SearchService

logger = structlog.get_logger("gamdl_web.formats")

# Same rewrite gamdl applies: the "_default" master lists every variant.
DEFAULT_MASTER_RE = re.compile(r"(P\d+)_[^/]+(\.m3u8)")
ALAC_RE = re.compile(r"audio-alac-stereo-(\d+)-(\d+)")
ATMOS_RE = re.compile(r"audio-atmos-(\d+)")
AC3_RE = re.compile(r"audio-ac3-(\d+)")
AAC_RE = re.compile(r"audio-(HE-)?stereo-(\d+)(?:-(binaural|downmix))?")
VARIANT_SUFFIX = {"binaural": "바이노럴", "downmix": "다운믹스"}


def _khz(rate: int) -> str:
    return f"{rate / 1000:g}kHz"


def describe(group: str, bandwidth: int | None) -> dict[str, Any] | None:
    """Turn an HLS audio group id like audio-alac-stereo-96000-24 into a format."""
    if m := ALAC_RE.fullmatch(group):
        rate, bits = int(m[1]), int(m[2])
        return {
            "group": group, "family": "alac", "name": "ALAC",
            "label": f"{bits}bit · {_khz(rate)}", "bits": bits, "rate": rate,
            "hires": rate > 48000, "rank": 3_000_000 + bits * 1000 + rate // 100,
        }
    if m := ATMOS_RE.fullmatch(group):
        n = int(m[1])
        kbps = n % 1000 if n > 2000 else n
        return {
            "group": group, "family": "atmos", "name": "Dolby Atmos",
            "label": f"{kbps}kbps", "kbps": kbps, "rank": 2_000_000 + kbps,
        }
    if m := AC3_RE.fullmatch(group):
        kbps = int(m[1]) % 1000
        return {
            "group": group, "family": "ac3", "name": "AC-3",
            "label": f"{kbps}kbps", "kbps": kbps, "rank": 1_500_000 + kbps,
        }
    if m := AAC_RE.fullmatch(group):
        he, kbps, variant = bool(m[1]), int(m[2]), m[3]
        name = "AAC-HE" if he else "AAC"
        if variant:
            name += f" {VARIANT_SUFFIX[variant]}"
        return {
            "group": group, "family": "aac-he" if he else "aac", "name": name,
            "label": f"{kbps}kbps", "kbps": kbps, "variant": variant,
            "rank": 1_000_000 + kbps * 10 - (5 if variant else 0) - (500 if he else 0),
        }
    logger.debug("unknown_audio_group", group=group, bandwidth=bandwidth)
    return None


class FormatService:
    """Looks up which audio formats Apple offers for a song (cached)."""

    def __init__(self, store: SettingsStore, search: SearchService) -> None:
        self.store = store
        self.search = search
        self._cache: OrderedDict[str, dict] = OrderedDict()
        # The wrapper worker serves one Apple request at a time.
        self._wrapper_slots = asyncio.Semaphore(2)

    def _remember(self, key: str, value: dict) -> dict:
        self._cache[key] = value
        self._cache.move_to_end(key)
        while len(self._cache) > 500:
            self._cache.popitem(last=False)
        return value

    async def _master_from_wrapper(self, client: httpx.AsyncClient, song_id: str) -> str | None:
        url = self.store.get().wrapper_url
        async with self._wrapper_slots:
            response = await client.get(f"{url}/playback", params={"adam_id": song_id}, timeout=30)
        if response.is_error:
            return None
        songs = response.json().get("songList") or [{}]
        return songs[0].get("hls-playlist-url")

    async def _master_from_catalog(self, song_id: str) -> str | None:
        api = await self.search._session()
        response = await self.search._client.get(
            f"{APPLE_MUSIC_AMP_API_URL}/v1/catalog/{api.storefront}/songs/{song_id}",
            params={"extend": "extendedAssetUrls"},
        )
        if response.is_error:
            return None
        data = response.json().get("data") or [{}]
        return (data[0].get("attributes") or {}).get("extendedAssetUrls", {}).get("enhancedHls")

    async def _first_track(self, kind: str, item_id: str) -> str | None:
        api = await self.search._session()
        response = await self.search._client.get(
            f"{APPLE_MUSIC_AMP_API_URL}/v1/catalog/{api.storefront}/{kind}/{item_id}/tracks",
            params={"limit": 1},
        )
        if response.is_error:
            return None
        tracks = [t for t in response.json().get("data", []) if t.get("type") == "songs"]
        return tracks[0]["id"] if tracks else None

    async def song_formats(self, song_id: str) -> dict[str, Any]:
        if song_id in self._cache:
            return self._cache[song_id]
        source = "wrapper"
        async with httpx.AsyncClient(timeout=15) as client:
            master = None
            if self.store.get().use_wrapper:
                try:
                    master = await self._master_from_wrapper(client, song_id)
                except httpx.HTTPError:
                    master = None
            if not master:
                # Without the wrapper the catalog playlist tops out at 48kHz.
                source = "catalog"
                master = await self._master_from_catalog(song_id)
            if not master:
                return {"id": song_id, "source": source, "formats": []}
            response = await client.get(DEFAULT_MASTER_RE.sub(r"\1_default\2", master))
            response.raise_for_status()
        playlists = m3u8.loads(response.text).data.get("playlists", [])
        formats = {}
        for playlist in playlists:
            info = playlist.get("stream_info") or {}
            group = info.get("audio")
            if group and group not in formats:
                described = describe(group, info.get("average_bandwidth"))
                if described:
                    formats[group] = described
        ordered = sorted(formats.values(), key=lambda f: f["rank"], reverse=True)
        best_alac = next((f for f in ordered if f["family"] == "alac"), None)
        if best_alac:
            best_alac["best"] = True
        return self._remember(song_id, {"id": song_id, "source": source, "formats": ordered})

    async def formats(self, kind: str, item_id: str) -> dict[str, Any]:
        if kind in {"songs", "library-songs"}:
            return await self.song_formats(item_id)
        # For collections the first track stands in for the rest.
        key = f"{kind}:{item_id}"
        if key in self._cache:
            return self._cache[key]
        song_id = await self._first_track(kind, item_id)
        if not song_id:
            return {"id": item_id, "source": None, "formats": [], "sample": None}
        result = dict(await self.song_formats(song_id))
        result["sample"] = song_id
        return self._remember(key, result)
