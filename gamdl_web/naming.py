"""File name templates written with %variables%, e.g. "%position% - %artist% - %title%".

gamdl's own {field} templates still work; %variables% are filled in first and
the result is handed to gamdl, which splits it into folders and cleans each part.
"""

from __future__ import annotations

import re
from typing import Any

# name -> what it holds (shown as the chip's tooltip in Settings)
VARIABLES: dict[str, str] = {
    "title": "제목",
    "artist": "아티스트 (Apple Music 표기 그대로)",
    "artists": "모든 아티스트, 쉼표로 구분 (피처링 포함)",
    "allartists": "메인 아티스트 feat. 피처링 아티스트",
    "mainartists": "메인 아티스트만",
    "featartists": "피처링 아티스트 (없으면 비어요)",
    "album": "앨범",
    "albumartist": "앨범 아티스트",
    "composer": "작곡가",
    "tracknumber": "앨범 트랙 번호 (01)",
    "tracktotal": "앨범 총 트랙 수",
    "discnumber": "디스크 번호",
    "disctotal": "총 디스크 수",
    "genre": "장르",
    "year": "발매 연도",
    "date": "발매일 (2024-05-01)",
    "label": "레이블",
    "isrc": "ISRC",
    "upc": "UPC",
    "explicit": "Explicit 곡이면 'Explicit', 아니면 비어요",
    "track_id": "Apple Music 곡 ID",
    "album_id": "Apple Music 앨범 ID",
    "artist_id": "Apple Music 아티스트 ID",
    "playlist": "플레이리스트 이름",
    "playlistartist": "플레이리스트 만든 사람",
    "playlist_id": "Apple Music 플레이리스트 ID",
    "position": "플레이리스트·목록 안의 순서 (01)",
}

VAR_RE = re.compile(r"%(" + "|".join(sorted(VARIABLES, key=len, reverse=True)) + r")%", re.IGNORECASE)

# Old {field} spellings and their %variable% equivalents, for converting saved templates.
LEGACY = {
    "{album}": "%album%",
    "{album_artist}": "%albumartist%",
    "{album_id}": "%album_id%",
    "{artist}": "%artist%",
    "{artist_id}": "%artist_id%",
    "{composer}": "%composer%",
    "{title}": "%title%",
    "{title_id}": "%track_id%",
    "{track:02d}": "%tracknumber%",
    "{track_total}": "%tracktotal%",
    "{disc}": "%discnumber%",
    "{disc_total}": "%disctotal%",
    "{date:%Y}": "%year%",
    "{playlist_title}": "%playlist%",
    "{playlist_artist}": "%playlistartist%",
    "{playlist_id}": "%playlist_id%",
    "{playlist_track:02d}": "%position%",
    "{playlist_track}": "%position%",
}

FEAT_RE = re.compile(r"\s*[(\[](?:feat\.?|ft\.?|featuring|with)\s+([^)\]]+)[)\]]", re.IGNORECASE)
ARTIST_SPLIT_RE = re.compile(r"\s*(?:,|&|\bx\b|\band\b)\s*", re.IGNORECASE)


def from_legacy(template: str) -> str:
    """The %variable% spelling of a {field} template, or the template unchanged
    when part of it has no equivalent."""
    out = template
    for old, new in LEGACY.items():
        out = out.replace(old, new)
    return template if "{" in out else out


def _split_artists(text: str) -> list[str]:
    return [a for a in ARTIST_SPLIT_RE.split(text or "") if a]


def _pad(value: Any, total: Any = None) -> str:
    if value in (None, ""):
        return ""
    width = max(2, len(str(total))) if total else 2
    return str(value).zfill(width)


def context(tags, playlist_tags=None, media=None, position=None, position_total=None) -> dict[str, str]:
    """Every variable's value for one item; missing ones are empty."""
    attrs = (media.media_metadata or {}).get("attributes", {}) if media else {}
    album = {}
    if media:
        albums = (media.media_metadata or {}).get("relationships", {}).get("albums", {}).get("data") or []
        album = (albums[0].get("attributes") or {}) if albums else {}

    title = tags.title or ""
    main = _split_artists(tags.artist or "")
    feat = []
    for m in FEAT_RE.finditer(title):
        feat += [a for a in _split_artists(m.group(1)) if a not in main]
    if playlist_tags and playlist_tags.track:
        position = playlist_tags.track
        position_total = position_total or (media.total if media else None)
    date = tags.date
    date_text = date.isoformat()[:10] if hasattr(date, "isoformat") else str(date or "")[:10]
    rating = getattr(tags.rating, "value", tags.rating)

    return {
        "title": title,
        "artist": tags.artist or "",
        "artists": ", ".join(main + feat),
        "allartists": ", ".join(main) + (" feat. " + ", ".join(feat) if feat else ""),
        "mainartists": ", ".join(main),
        "featartists": ", ".join(feat),
        "album": tags.album or "",
        "albumartist": tags.album_artist or "",
        "composer": tags.composer or "",
        "tracknumber": _pad(tags.track, tags.track_total),
        "tracktotal": str(tags.track_total or ""),
        "discnumber": str(tags.disc or ""),
        "disctotal": str(tags.disc_total or ""),
        "genre": tags.genre or "",
        "year": date_text[:4],
        "date": date_text,
        "label": album.get("recordLabel") or "",
        "isrc": attrs.get("isrc") or "",
        "upc": album.get("upc") or "",
        "explicit": "Explicit" if rating == 1 else "",
        "track_id": str(tags.title_id or ""),
        "album_id": str(tags.album_id or ""),
        "artist_id": str(tags.artist_id or ""),
        "playlist": (playlist_tags.title if playlist_tags else "") or "",
        "playlistartist": (playlist_tags.artist if playlist_tags else "") or "",
        "playlist_id": str((playlist_tags.playlist_id if playlist_tags else "") or ""),
        "position": _pad(position, position_total),
    }


EMPTY = "\x00"


def _tidy(part: str) -> str:
    """Drop empty variables together with their brackets or the separator before
    them, so "%title% (%featartists%)" doesn't end in "()". Title text is untouched."""
    part = re.sub(r"\s*[(\[]\x00[)\]]", "", part)
    part = re.sub(r"^\x00\s*[-–_,.]?\s*", "", part)
    part = re.sub(r"\s*[-–_,.]?\s*\x00", "", part)
    return re.sub(r"\s{2,}", " ", part).strip()


def expand(template: str, values: dict[str, str]) -> str:
    """Fill in %variables%, leaving {fields} for gamdl. Values can't add folders
    or be read as {fields}."""
    if "%" not in template:
        return template

    def value(m: re.Match) -> str:
        v = values.get(m.group(1).lower(), "")
        return v.replace("/", "_").replace("\\", "_").replace("{", "{{").replace("}", "}}") or EMPTY

    parts = []
    for part in template.split("/"):
        parts.append(_tidy(VAR_RE.sub(value, part)) or "Unknown" if VAR_RE.search(part) else part)
    return "/".join(parts)
