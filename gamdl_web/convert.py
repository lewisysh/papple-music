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
from mutagen.aiff import AIFF
from mutagen.wave import WAVE
from PIL import Image

# Only real lossless sources become FLAC/WAV; Dolby streams are left alone.
LOSSLESS_CODECS = {"alac", "flac", "pcm_s16le", "pcm_s24le", "pcm_s16be", "pcm_s24be"}
SURROUND_CODECS = {"eac3", "ac3"}
EXTENSIONS = {"flac": ".flac", "wav": ".wav", "aiff": ".aiff", "mp3": ".mp3"}

# Tags gamdl does not write; stored in the m4a as iTunes freeform atoms so the
# converters below can carry them over from a single source.
EXTRA_TAGS = {"label": "LABEL", "upc": "UPC", "url": "URL", "language": "LANGUAGE"}
FREEFORM = "----:com.apple.iTunes:"


# Sample entry types of audio or video that is still encrypted: HLS FairPlay or
# CENC ("enca"/"encv") and iTunes-style protected files ("drms"/"drmi").
PROTECTED_ENTRIES = {b"enca", b"encv", b"drms", b"drmi"}
# Boxes on the way from the top of an MP4 to its sample descriptions.
_STSD_PATH = (b"moov", b"trak", b"mdia", b"minf", b"stbl", b"stsd")


def _boxes(data: bytes, start: int = 0, end: int | None = None):
    """(type, body start, end) of each box in data[start:end]."""
    end = len(data) if end is None else end
    while start + 8 <= end:
        size, kind, body = int.from_bytes(data[start:start + 4], "big"), data[start + 4:start + 8], start + 8
        if size == 1:
            size, body = int.from_bytes(data[start + 8:start + 16], "big"), start + 16
        elif size == 0:
            size = end - start
        if size < body - start or start + size > end:
            return
        yield kind, body, start + size
        start += size


def _sample_entries(moov: bytes, depth: int = 1, start: int = 0, end: int | None = None):
    for kind, body, box_end in _boxes(moov, start, end):
        if kind != _STSD_PATH[depth]:
            continue
        if kind == b"stsd":
            # version/flags and entry count come before the entries.
            yield from (k for k, _, _ in _boxes(moov, body + 8, box_end))
        else:
            yield from _sample_entries(moov, depth + 1, body, box_end)


def head_is_protected(data: bytes) -> bool | None:
    """Like is_protected, for the start of a file: None when its moov isn't in data."""
    for kind, body, end in _boxes(data):
        if kind == b"moov":
            return any(e in PROTECTED_ENTRIES for e in _sample_entries(data, 1, body, end))
    return None


AAC_RATES = (96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000, 7350)


class _Bits:
    def __init__(self, data: bytes):
        self.data, self.pos = data, 0

    def left(self) -> int:
        return len(self.data) * 8 - self.pos

    def read(self, n: int) -> int:
        if n > self.left():
            raise ValueError("out of bits")
        value = 0
        for _ in range(n):
            value = (value << 1) | (self.data[self.pos >> 3] >> (7 - (self.pos & 7)) & 1)
            self.pos += 1
        return value


def _sbr_rates(asc: bytes) -> tuple[int, int] | None:
    """(core, output) sample rates of an HE-AAC AudioSpecificConfig, or None
    when it has no SBR (plain AAC)."""
    bits = _Bits(asc)

    def object_type() -> int:
        kind = bits.read(5)
        return 32 + bits.read(6) if kind == 31 else kind

    def rate() -> int:
        index = bits.read(4)
        return bits.read(24) if index == 15 else AAC_RATES[index]

    try:
        kind, core = object_type(), rate()
        bits.read(4)  # channels
        if kind in (5, 29):  # SBR / PS signalled up front
            return core, rate()
        if kind == 2 and bits.left() >= 3 + 16:
            bits.read(3)  # GASpecificConfig
            if bits.read(11) == 0x2B7 and object_type() == 5 and bits.read(1):
                return core, rate()
    except (ValueError, IndexError):
        pass
    return None


def _esds_asc(esds: bytes) -> bytes | None:
    """The AudioSpecificConfig inside an esds box body."""

    def descriptor(pos: int) -> tuple[int, int, int]:
        tag, pos, size = esds[pos], pos + 1, 0
        for _ in range(4):
            byte, pos = esds[pos], pos + 1
            size = size << 7 | byte & 0x7F
            if not byte & 0x80:
                break
        return tag, pos, size

    try:
        tag, pos, _ = descriptor(4)
        if tag != 3:
            return None
        flags, pos = esds[pos + 2], pos + 3
        if flags & 0x80:
            pos += 2
        if flags & 0x40:
            pos += 1 + esds[pos]
        if flags & 0x20:
            pos += 2
        tag, pos, _ = descriptor(pos)
        if tag != 4:
            return None
        tag, pos, size = descriptor(pos + 13)
        return esds[pos:pos + size] if tag == 5 else None
    except IndexError:
        return None


def _read_moov(f) -> tuple[int, bytes] | None:
    """(file offset, bytes) of the moov box, header included."""
    f.seek(0)
    offset = 0
    while True:
        header = f.read(8)
        if len(header) < 8:
            return None
        size, kind, read = int.from_bytes(header[:4], "big"), header[4:], 8
        if size == 1:
            size, read = int.from_bytes(f.read(8), "big"), 16
        if kind == b"moov":
            f.seek(offset)
            return offset, f.read(size) if size else f.read()
        if size == 0 or size < read:
            return None
        offset += size
        f.seek(offset)


def fix_sbr_timescale(path: str) -> bool:
    """gamdl's muxer gives HE-AAC audio the core sample rate (22050) as its
    timescale but writes each frame's length in output samples (2048 at 44100),
    so the audio reads twice as long as it is: a 3:56 video shows 7:52, with no
    picture after 3:56. Sets the timescale to the output rate in place and fixes
    the lengths built from it. True when the file needed it."""
    with open(path, "r+b") as f:
        found = _read_moov(f)
        if not found:
            return False
        base, moov = found

        def child(kind: bytes, start: int, end: int):
            return next(((b, e) for k, b, e in _boxes(moov, start, end) if k == kind), None)

        def field(offset: int, size: int) -> int:
            return int.from_bytes(moov[offset:offset + size], "big")

        def timing(body: int) -> tuple[int, int, int, int]:
            """(timescale offset, duration offset, duration size) of an mvhd/mdhd."""
            return (body + 12, body + 16, 4) if moov[body] == 0 else (body + 20, body + 24, 8)

        top = next(((b, e) for k, b, e in _boxes(moov) if k == b"moov"), None)
        mvhd = child(b"mvhd", *top) if top else None
        if not mvhd or any(k == b"mvex" for k, _, _ in _boxes(moov, *top)):
            return False
        movie_scale_at, movie_duration_at, movie_duration_size = timing(mvhd[0])
        movie_scale = field(movie_scale_at, 4)

        patches, track_durations = [], []
        for kind, body, end in _boxes(moov, *top):
            if kind != b"trak":
                continue
            tkhd = child(b"tkhd", body, end)
            tkhd_at, tkhd_size = (tkhd[0] + 20, 4) if moov[tkhd[0]] == 0 else (tkhd[0] + 28, 8)
            track_duration = field(tkhd_at, tkhd_size)
            mdia = child(b"mdia", body, end)
            hdlr = child(b"hdlr", *mdia) if mdia else None
            stbl = child(b"stbl", *child(b"minf", *mdia)) if mdia and child(b"minf", *mdia) else None
            if hdlr and stbl and moov[hdlr[0] + 8:hdlr[0] + 12] == b"soun" and not child(b"edts", body, end):
                mdhd = child(b"mdhd", *mdia)
                scale_at, duration_at, duration_size = timing(mdhd[0])
                scale, media_duration = field(scale_at, 4), field(duration_at, duration_size)
                stsd, stts = child(b"stsd", *stbl), child(b"stts", *stbl)
                entry = next(iter(_boxes(moov, stsd[0] + 8, stsd[1])), None) if stsd else None
                esds = child(b"esds", entry[1] + 28, entry[2]) if entry and entry[0] == b"mp4a" else None
                rates = _sbr_rates(_esds_asc(moov[esds[0]:esds[1]]) or b"") if esds else None
                deltas = [(field(stts[0] + 8 + i * 8, 4), field(stts[0] + 12 + i * 8, 4))
                          for i in range(field(stts[0] + 4, 4))] if stts else []
                frame = max(deltas)[1] if deltas else 0
                if rates and frame == 2048 and scale == rates[0] and rates[1] == 2 * rates[0]:
                    patches.append((scale_at, 4, rates[1]))
                    track_duration = round(media_duration * movie_scale / rates[1])
                    patches.append((tkhd_at, tkhd_size, track_duration))
            track_durations.append(track_duration)

        if not patches:
            return False
        patches.append((movie_duration_at, movie_duration_size, max(track_durations)))
        for offset, size, value in patches:
            f.seek(base + offset)
            f.write(value.to_bytes(size, "big"))
    return True


VIDEO_CODECS = {b"avc1": "h264", b"avc3": "h264", b"hvc1": "hevc", b"hev1": "hevc", b"dvh1": "hevc", b"dvhe": "hevc"}


def video_quality(path: str) -> dict | None:
    """What a downloaded video really is, read from its first video track:
    {"video": True, "codec": "h264"|"hevc", "width": 1674, "height": 1080}."""
    try:
        with open(path, "rb") as f:
            found = _read_moov(f)
    except OSError:
        return None
    if not found:
        return None
    moov = found[1]
    top = next(((b, e) for k, b, e in _boxes(moov) if k == b"moov"), None)
    for kind, body, end in _boxes(moov, *top) if top else ():
        if kind != b"trak":
            continue
        path_boxes = (b"mdia", b"minf", b"stbl", b"stsd")
        start, stop = body, end
        for name in path_boxes:
            box = next(((b, e) for k, b, e in _boxes(moov, start, stop) if k == name), None)
            if not box:
                break
            start, stop = box
        else:
            entry = next(iter(_boxes(moov, start + 8, stop)), None)
            if entry and entry[0] in VIDEO_CODECS:
                at = entry[1] + 24
                return {
                    "video": True,
                    "codec": VIDEO_CODECS[entry[0]],
                    "width": int.from_bytes(moov[at:at + 2], "big"),
                    "height": int.from_bytes(moov[at + 2:at + 4], "big"),
                }
    return None


def is_protected(path: str) -> bool:
    """Whether an MP4 file is still DRM-encrypted, which nothing but Apple's
    Music app can play."""
    with open(path, "rb") as f:
        while True:
            header = f.read(8)
            if len(header) < 8:
                return False
            size, kind, read = int.from_bytes(header[:4], "big"), header[4:], 8
            if size == 1:
                size, read = int.from_bytes(f.read(8), "big"), 16
            if kind == b"moov":
                moov = f.read(size - read) if size else f.read()
                return any(e in PROTECTED_ENTRIES for e in _sample_entries(moov))
            if size == 0 or size < read:
                return False
            f.seek(size - read, 1)


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
        "bit_rate": str(getattr(info, "bitrate", 0) or ""),
    }


async def probe(path: str, ffprobe: str) -> dict:
    if not (shutil.which(ffprobe) or Path(ffprobe).is_file()):
        return await asyncio.to_thread(_probe_tags, path)
    out = await _run(
        ffprobe, "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=codec_name,sample_rate,bits_per_raw_sample,bits_per_sample,channels,bit_rate",
        "-of", "json", path,
    )
    streams = json.loads(out).get("streams") or [{}]
    return streams[0]


def _nominal_kbps(bit_rate: int) -> int:
    """Measured bitrates wobble (257k for Apple's 256k AAC); snap to the usual ones."""
    kbps = bit_rate / 1000
    for nominal in (64, 96, 128, 160, 192, 256, 320, 384, 448, 640, 768):
        if abs(kbps - nominal) <= nominal * 0.04:
            return nominal
    return round(kbps)


async def audio_quality(path: str, ffmpeg: str = "ffmpeg") -> dict | None:
    """What a downloaded file really is, for the Downloads page:
    {"codec": "alac"|"aac"|"eac3"|..., "bits": 24, "rate": 96000, "kbps": 256}."""
    try:
        info = await probe(path, _ffprobe_for(shutil.which(ffmpeg) or ffmpeg))
    except (ConvertError, OSError, ValueError):
        return None

    def number(key: str) -> int | None:
        try:
            return int(float(info.get(key) or 0)) or None
        except (TypeError, ValueError):
            return None

    codec = (info.get("codec_name") or "").lower() or None
    bits = number("bits_per_raw_sample") or number("bits_per_sample")
    bit_rate = number("bit_rate")
    return {
        "codec": codec,
        "bits": bits if codec in LOSSLESS_CODECS else None,
        "rate": number("sample_rate"),
        "kbps": _nominal_kbps(bit_rate) if bit_rate and codec not in LOSSLESS_CODECS else None,
        "channels": info.get("channels"),
    }


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
    audio = MP3(path) if kind == "mp3" else AIFF(path) if kind == "aiff" else WAVE(path)
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
    if output_format in {"flac", "wav", "aiff"} and codec not in LOSSLESS_CODECS:
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
    elif output_format == "aiff":
        # What DJ software and CDJs read most reliably, tags (ID3) included.
        args += ["-c:a", "pcm_s24be" if bits > 16 else "pcm_s16be", "-f", "aiff"]
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
