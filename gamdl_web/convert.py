from __future__ import annotations

import asyncio
import io
import json
import os
import re
import shutil
from pathlib import Path

import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.id3 import (
    APIC, COMM, TALB, TCMP, TCOM, TCON, TCOP, TDRC, TIT2, TPE1, TPE2, TPOS, TPUB,
    TRCK, TSO2, TSOA, TSOC, TSOP, TSOT, TSRC, TXXX, USLT, WOAS,
)
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm
from mutagen.wave import WAVE
from PIL import Image

# Only real lossless sources become FLAC/WAV; Dolby streams are left alone.
LOSSLESS_CODECS = {"alac", "flac", "pcm_s16le", "pcm_s24le"}
SURROUND_CODECS = {"eac3", "ac3"}
EXTENSIONS = {"flac": ".flac", "wav": ".wav", "mp3": ".mp3"}

# Tags gamdl does not write; stored in the m4a as iTunes freeform atoms so the
# converters below can carry them over from a single source.
EXTRA_TAGS = {"label": "LABEL", "upc": "UPC", "url": "URL", "language": "LANGUAGE"}
FREEFORM = "----:com.apple.iTunes:"


class ConvertError(Exception):
    pass


async def _run(*args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise ConvertError(err.decode(errors="replace").strip()[-400:] or f"exit {proc.returncode}")
    return out.decode(errors="replace")


MP4_CODECS = {"alac": "alac", "ec-3": "eac3", "ac-3": "ac3"}


def _probe_tags(path: str) -> dict:
    """ffprobe-style stream info from mutagen, for setups without ffprobe (the Mac app)."""
    audio = mutagen.File(path)
    if audio is None:
        raise ConvertError(f"unknown audio format: {path}")
    info = audio.info
    if isinstance(audio, FLAC):
        codec = "flac"
    else:
        raw = (getattr(info, "codec", "") or "").lower()
        codec = MP4_CODECS.get(raw, "aac" if raw.startswith("mp4a") else raw or "unknown")
    return {
        "codec_name": codec,
        "sample_rate": str(getattr(info, "sample_rate", 0) or ""),
        "bits_per_raw_sample": str(getattr(info, "bits_per_sample", 0) or ""),
        "channels": getattr(info, "channels", None),
    }


async def probe(path: str, ffprobe: str) -> dict:
    if not (shutil.which(ffprobe) or Path(ffprobe).is_file()):
        return await asyncio.to_thread(_probe_tags, path)
    out = await _run(
        ffprobe, "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=codec_name,sample_rate,bits_per_raw_sample,bits_per_sample,channels",
        "-of", "json", path,
    )
    streams = json.loads(out).get("streams") or [{}]
    return streams[0]


def extra_tags(media_metadata: dict | None) -> dict:
    metadata = media_metadata or {}
    attributes = metadata.get("attributes") or {}
    albums = ((metadata.get("relationships") or {}).get("albums") or {}).get("data") or [{}]
    album = albums[0].get("attributes") or {}
    return {
        "label": album.get("recordLabel"),
        "upc": album.get("upc"),
        "url": attributes.get("url"),
        "language": attributes.get("audioLocale"),
    }


def write_mp4_extras(path: str, extras: dict, exclude_tags: list[str]) -> None:
    if "all" in exclude_tags:
        return
    mp4 = MP4(path)
    if mp4.tags is None:
        mp4.add_tags()
    for key, atom in EXTRA_TAGS.items():
        value = extras.get(key)
        if value and key not in exclude_tags:
            mp4.tags[FREEFORM + atom] = [MP4FreeForm(str(value).encode())]
    mp4.save()


def target_path(source: str, output_format: str) -> str:
    return str(Path(source).with_suffix(EXTENSIONS[output_format]))


def _ffprobe_for(ffmpeg: str) -> str:
    sibling = Path(ffmpeg).with_name("ffprobe")
    return str(sibling) if sibling.exists() else shutil.which("ffprobe") or "ffprobe"


def _mp4_tags(source: str) -> dict:
    mp4 = MP4(source)
    tags = mp4.tags or {}

    def first(key):
        value = tags.get(key)
        return value[0] if value else None

    track = first("trkn") or (None, None)
    disc = first("disk") or (None, None)
    cover = first("covr")
    freeform = {
        key: bytes(tags[FREEFORM + atom][0]).decode(errors="replace")
        for key, atom in EXTRA_TAGS.items()
        if tags.get(FREEFORM + atom)
    }
    xid = first("xid ") or ""
    isrc = xid.rsplit(":", 1)[-1] if ":isrc:" in xid else None
    date = first("\xa9day")
    return {
        "title": first("\xa9nam"),
        "artist": first("\xa9ART"),
        "album": first("\xa9alb"),
        "albumartist": first("aART"),
        "composer": first("\xa9wrt"),
        "genre": first("\xa9gen"),
        "date": date[:10] if date else None,
        "track": track[0] or None,
        "tracktotal": track[1] or None,
        "disc": disc[0] or None,
        "disctotal": disc[1] or None,
        "copyright": first("cprt"),
        "lyrics": first("\xa9lyr"),
        "comment": first("\xa9cmt"),
        "albumsort": first("soal"),
        "artistsort": first("soar"),
        "titlesort": first("sonm"),
        "composersort": first("soco"),
        "albumartistsort": first("soaa"),
        "compilation": tags.get("cpil"),
        # iTunes advisory: 0 none, 1 explicit, 2 clean; None when the tag was excluded.
        "rating": first("rtng"),
        "isrc": isrc,
        "apple_id": first("cnID"),
        **{key: freeform.get(key) for key in EXTRA_TAGS},
        "cover": bytes(cover) if cover is not None else None,
        "cover_mime": (
            "image/png" if cover is not None and cover.imageformat == MP4Cover.FORMAT_PNG else "image/jpeg"
        ),
    }


def _write_flac(path: str, t: dict) -> None:
    audio = FLAC(path)
    audio.clear()
    fields = {
        "TITLE": t["title"], "ARTIST": t["artist"], "ALBUM": t["album"],
        "ALBUMARTIST": t["albumartist"], "COMPOSER": t["composer"], "GENRE": t["genre"],
        "DATE": t["date"], "TRACKNUMBER": t["track"], "TRACKTOTAL": t["tracktotal"],
        "DISCNUMBER": t["disc"], "DISCTOTAL": t["disctotal"], "COPYRIGHT": t["copyright"],
        "LYRICS": t["lyrics"], "COMMENT": t["comment"], "ALBUMSORT": t["albumsort"],
        "ARTISTSORT": t["artistsort"], "TITLESORT": t["titlesort"],
        "COMPOSERSORT": t["composersort"], "ALBUMARTISTSORT": t["albumartistsort"],
        "ISRC": t["isrc"], "COMPILATION": "1" if t["compilation"] else None,
        "LABEL": t["label"], "UPC": t["upc"], "WEBSITE": t["url"], "LANGUAGE": t["language"],
        "APPLE_MUSICID": t["apple_id"],
        "ITUNESADVISORY": t["rating"],
        "EXPLICIT": None if t["rating"] is None else str(int(t["rating"] == 1)),
    }
    for key, value in fields.items():
        if value not in (None, ""):
            audio[key] = str(value)
    audio.clear_pictures()
    if t["cover"]:
        picture = Picture()
        picture.type = 3
        picture.mime = t["cover_mime"]
        picture.data = t["cover"]
        with Image.open(io.BytesIO(t["cover"])) as image:
            picture.width, picture.height = image.size
            picture.depth = 24
        audio.add_picture(picture)
    audio.save()


def _id3_frames(t: dict) -> list:
    def number(n, total):
        return f"{n}/{total}" if total else str(n)

    frames = []
    simple = [
        (TIT2, "title"), (TPE1, "artist"), (TALB, "album"), (TPE2, "albumartist"),
        (TCOM, "composer"), (TCON, "genre"), (TDRC, "date"), (TCOP, "copyright"),
        (TSOA, "albumsort"), (TSOP, "artistsort"), (TSOT, "titlesort"),
        (TSOC, "composersort"), (TSO2, "albumartistsort"), (TSRC, "isrc"),
    ]
    for frame, key in simple:
        if t[key]:
            frames.append(frame(encoding=3, text=str(t[key])))
    if t["track"]:
        frames.append(TRCK(encoding=3, text=number(t["track"], t["tracktotal"])))
    if t["disc"]:
        frames.append(TPOS(encoding=3, text=number(t["disc"], t["disctotal"])))
    if t["compilation"]:
        frames.append(TCMP(encoding=3, text="1"))
    if t["label"]:
        frames.append(TPUB(encoding=3, text=t["label"]))
    if t["url"]:
        frames.append(WOAS(url=t["url"]))
    custom = {
        "UPC": t["upc"], "LANGUAGE": t["language"], "APPLE_MUSICID": t["apple_id"],
        "ITUNESADVISORY": t["rating"],
        "EXPLICIT": None if t["rating"] is None else int(t["rating"] == 1),
    }
    for desc, value in custom.items():
        if value is not None and value != "":
            frames.append(TXXX(encoding=3, desc=desc, text=str(value)))
    if t["lyrics"]:
        frames.append(USLT(encoding=3, lang="und", desc="", text=t["lyrics"]))
    if t["comment"]:
        frames.append(COMM(encoding=3, lang="und", desc="", text=t["comment"]))
    if t["cover"]:
        frames.append(APIC(encoding=3, mime=t["cover_mime"], type=3, desc="Cover", data=t["cover"]))
    return frames


def _write_id3(path: str, t: dict, kind: str) -> None:
    audio = MP3(path) if kind == "mp3" else WAVE(path)
    if audio.tags is None:
        audio.add_tags()
    audio.tags.clear()
    for frame in _id3_frames(t):
        audio.tags.add(frame)
    audio.save(v2_version=3) if kind == "mp3" else audio.save()


async def convert(
    source: str,
    output_format: str,
    ffmpeg: str = "ffmpeg",
    mp3_bitrate: str = "320k",
    keep_original: bool = False,
) -> tuple[str | None, str]:
    """Convert a downloaded .m4a; returns (new path or None if kept, note)."""
    ffmpeg = shutil.which(ffmpeg) or ffmpeg
    info = await probe(source, _ffprobe_for(ffmpeg))
    codec = info.get("codec_name")
    if codec in SURROUND_CODECS:
        return None, "Dolby 음원이라 m4a 그대로 둠"
    if output_format in {"flac", "wav"} and codec not in LOSSLESS_CODECS:
        return None, f"손실 음원({codec})이라 {output_format.upper()} 변환 안 함"

    bits = int(info.get("bits_per_raw_sample") or info.get("bits_per_sample") or 16)
    target = target_path(source, output_format)
    part = f"{target}.part"
    args = [ffmpeg, "-y", "-v", "error", "-i", source, "-map", "0:a:0", "-map_metadata", "-1"]
    if output_format == "flac":
        args += ["-c:a", "flac", "-compression_level", "8"]
        if bits > 16:
            args += ["-sample_fmt", "s32", "-bits_per_raw_sample", "24"]
        args += ["-f", "flac"]
    elif output_format == "wav":
        args += ["-c:a", "pcm_s24le" if bits > 16 else "pcm_s16le", "-f", "wav"]
    else:
        quality = ["-q:a", "0"] if mp3_bitrate == "V0" else ["-b:a", mp3_bitrate]
        args += ["-c:a", "libmp3lame", *quality, "-id3v2_version", "3", "-f", "mp3"]
    try:
        await _run(*args, part)
        tags = await asyncio.to_thread(_mp4_tags, source)
        if output_format == "flac":
            await asyncio.to_thread(_write_flac, part, tags)
        else:
            await asyncio.to_thread(_write_id3, part, tags, output_format)
        os.replace(part, target)
    finally:
        if os.path.exists(part):
            os.remove(part)
    if not keep_original:
        os.remove(source)
    rate = info.get("sample_rate")
    detail = f"{bits}bit · {int(rate) / 1000:g}kHz" if output_format != "mp3" and rate else mp3_bitrate
    return target, f"{output_format.upper()} 변환 ({detail})"


def retarget_playlist(playlist_file: str, old_path: str, new_path: str) -> None:
    """Point an m3u8 written by gamdl at the converted file."""
    path = Path(playlist_file)
    if not path.exists():
        return
    base = path.parent.absolute()
    old_rel = os.path.relpath(Path(old_path).absolute(), base).replace(os.sep, "/")
    new_rel = os.path.relpath(Path(new_path).absolute(), base).replace(os.sep, "/")
    text = path.read_text(encoding="utf8")
    updated = re.sub(rf"^{re.escape(old_rel)}$", new_rel.replace("\\", "\\\\"), text, flags=re.M)
    if updated != text:
        path.write_text(updated, encoding="utf8", newline="\n")
