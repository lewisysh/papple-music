from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

import re

import m3u8
from gamdl.interface import ArtistMediaType
from gamdl.interface.constants import SONG_CODEC_REGEX_MAP

from .events import EventBus

ARTIST_MEDIA_TYPE_LABELS = {
    ArtistMediaType.MAIN_ALBUMS: "정규 앨범",
    ArtistMediaType.COMPILATION_ALBUMS: "컴필레이션 앨범",
    ArtistMediaType.LIVE_ALBUMS: "라이브 앨범",
    ArtistMediaType.SINGLES_EPS: "싱글 & EP",
    ArtistMediaType.ALL_ALBUMS: "모든 앨범",
    ArtistMediaType.TOP_SONGS: "인기곡",
    ArtistMediaType.MUSIC_VIDEOS: "뮤직비디오",
}


class PromptCancelledError(Exception):
    def __init__(self) -> None:
        super().__init__("사용자가 선택을 취소했습니다")


@dataclass
class Prompt:
    title: str
    choices: list[dict[str, Any]]
    multiple: bool
    job_id: str | None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    future: asyncio.Future = field(
        default_factory=lambda: asyncio.get_running_loop().create_future()
    )

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "job_id": self.job_id,
            "title": self.title,
            "choices": self.choices,
            "multiple": self.multiple,
        }


class PromptBroker:
    """Turns gamdl's interactive questions into browser dialogs."""

    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self.pending: dict[str, Prompt] = {}

    async def ask(
        self,
        title: str,
        choices: list[dict[str, Any]],
        multiple: bool = False,
        job_id: str | None = None,
    ) -> list[int]:
        prompt = Prompt(title=title, choices=choices, multiple=multiple, job_id=job_id)
        self.pending[prompt.id] = prompt
        self.bus.publish("prompt", prompt.public())
        try:
            return await prompt.future
        finally:
            self.pending.pop(prompt.id, None)
            self.bus.publish("prompt_closed", {"id": prompt.id})

    def answer(self, prompt_id: str, selected: list[int]) -> None:
        prompt = self.pending.get(prompt_id)
        if prompt is None or prompt.future.done():
            raise KeyError(prompt_id)
        if any(i < 0 or i >= len(prompt.choices) for i in selected):
            raise ValueError("선택 항목이 범위를 벗어났습니다")
        if not prompt.multiple and len(selected) != 1:
            raise ValueError("하나만 선택해야 합니다")
        prompt.future.set_result(sorted(set(selected)))

    def cancel(self, prompt_id: str) -> None:
        prompt = self.pending.get(prompt_id)
        if prompt is None or prompt.future.done():
            raise KeyError(prompt_id)
        prompt.future.set_exception(PromptCancelledError())

    def cancel_job(self, job_id: str) -> None:
        for prompt in list(self.pending.values()):
            if prompt.job_id == job_id and not prompt.future.done():
                prompt.future.cancel()

    def snapshot(self) -> list[dict[str, Any]]:
        return [p.public() for p in self.pending.values()]


def _artwork(attributes: dict, size: int = 120) -> str | None:
    url = (attributes.get("artwork") or {}).get("url")
    if not url:
        return None
    return url.replace("{w}", str(size)).replace("{h}", str(size)).replace("{f}", "jpg")


def _duration(millis: int | None) -> str:
    if not millis:
        return ""
    minutes, seconds = divmod(millis // 1000, 60)
    return f"{minutes}:{seconds:02}"


def _rating(attributes: dict) -> str | None:
    rating = attributes.get("contentRating")
    return {"explicit": "🅴", "clean": "Clean"}.get(rating, rating)


def _join(*parts: Any) -> str:
    return " · ".join(str(p) for p in parts if p)


class WebPrompts:
    """Implements the callbacks gamdl's CLI answers with InquirerPy."""

    def __init__(
        self,
        broker: PromptBroker,
        job_id: str,
        artist_auto_select: ArtistMediaType | None = None,
        preferred_variant: str = "",
    ) -> None:
        self.broker = broker
        self.job_id = job_id
        self.artist_auto_select = artist_auto_select
        self.preferred_variant = preferred_variant

    async def _ask_one(self, title: str, choices: list[dict]) -> int:
        (index,) = await self.broker.ask(title, choices, job_id=self.job_id)
        return index

    def _pick_variant(self, playlists: list[dict]) -> dict:
        """Answer the codec question from the format chosen in the download sheet."""
        by_group = {p.get("stream_info", {}).get("audio"): p for p in playlists}
        if self.preferred_variant in by_group:
            return by_group[self.preferred_variant]
        # Another track may not offer the exact variant: take the best of the
        # same codec family, then the best ALAC, then AAC 256.
        family = next(
            (rx for rx in SONG_CODEC_REGEX_MAP.values() if re.fullmatch(rx, self.preferred_variant)),
            None,
        )
        for pattern in filter(None, [family, SONG_CODEC_REGEX_MAP["alac"], r"audio-stereo-256"]):
            matches = [
                p for p in playlists
                if re.fullmatch(pattern, p.get("stream_info", {}).get("audio") or "")
            ]
            if matches:
                return max(matches, key=lambda p: p["stream_info"].get("average_bandwidth") or 0)
        return max(playlists, key=lambda p: p["stream_info"].get("average_bandwidth") or 0)

    async def ask_song_codec(self, playlists: list[dict]) -> dict:
        if self.preferred_variant:
            return self._pick_variant(playlists)
        choices = []
        for playlist in playlists:
            info = playlist.get("stream_info", {})
            bandwidth = info.get("average_bandwidth") or info.get("bandwidth")
            choices.append(
                {
                    "label": info.get("audio") or info.get("codecs") or "unknown",
                    "detail": _join(
                        info.get("codecs"),
                        f"{bandwidth // 1000} kbps" if bandwidth else None,
                    ),
                }
            )
        index = await self._ask_one("다운로드할 오디오 코덱을 선택하세요", choices)
        return playlists[index]

    async def ask_music_video_video_codec(
        self, playlists: list[m3u8.Playlist]
    ) -> m3u8.Playlist:
        choices = [
            {
                "label": "x".join(str(v) for v in p.stream_info.resolution),
                "detail": _join(
                    p.stream_info.codecs[:4], f"{p.stream_info.bandwidth // 1000} kbps"
                ),
            }
            for p in playlists
        ]
        index = await self._ask_one("뮤직비디오 화질/코덱을 선택하세요", choices)
        return playlists[index]

    async def ask_music_video_audio_codec(self, playlists: list[dict]) -> dict:
        choices = [{"label": p["group_id"]} for p in playlists]
        index = await self._ask_one("뮤직비디오 오디오 코덱을 선택하세요", choices)
        return playlists[index]

    async def ask_uploaded_video_quality(self, qualities: dict[str, str]) -> str:
        keys = list(qualities)
        index = await self._ask_one(
            "영상 화질을 선택하세요", [{"label": k} for k in keys]
        )
        return qualities[keys[index]]

    async def ask_artist_media_type(
        self,
        media_types: list[ArtistMediaType],
        artist_metadata: dict,
    ) -> ArtistMediaType:
        if self.artist_auto_select:
            return self.artist_auto_select

        def count(media_type: ArtistMediaType) -> int:
            relation_key, type_key = media_type.path_key
            relation = artist_metadata.get(relation_key, {}).get(type_key, {})
            return len(relation.get("data") or [])

        available = [m for m in media_types if count(m)]
        if not available:
            return media_types[0]

        attributes = artist_metadata.get("attributes", {})
        index = await self._ask_one(
            f'"{attributes.get("name", "아티스트")}" — 무엇을 다운로드할까요?',
            [
                {
                    "label": ARTIST_MEDIA_TYPE_LABELS.get(m, str(m)),
                    "detail": f"{count(m)}개 이상",
                }
                for m in available
            ],
        )
        return available[index]

    async def ask_artist_select_items(
        self,
        media_type: ArtistMediaType,
        items: list[dict],
    ) -> list[dict]:
        items = [item for item in items if item.get("attributes")]
        if self.artist_auto_select:
            return items

        choices = []
        for item in items:
            attributes = item["attributes"]
            if item["type"] in {"albums", "library-albums"}:
                detail = _join(
                    f'{attributes.get("trackCount", "?")}곡',
                    attributes.get("releaseDate"),
                    _rating(attributes),
                )
            else:
                detail = _join(
                    _duration(attributes.get("durationInMillis")),
                    attributes.get("albumName"),
                    _rating(attributes),
                )
            choices.append(
                {
                    "label": attributes.get("name", item.get("id")),
                    "detail": detail,
                    "image": _artwork(attributes),
                }
            )

        selected = await self.broker.ask(
            f"{ARTIST_MEDIA_TYPE_LABELS.get(media_type, str(media_type))} — 다운로드할 항목을 고르세요",
            choices,
            multiple=True,
            job_id=self.job_id,
        )
        return [items[i] for i in selected]
