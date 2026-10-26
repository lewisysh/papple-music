"""Key and BPM tags for DJ software.

Apple Music has neither, so each downloaded song looks them up, in order:
1. the user's own copy of the song (tags written by rekordbox, Serato or
   Mixed In Key), found in a folder they point at;
2. GetSongBPM (key and BPM, needs the user's free API key);
3. Deezer by ISRC, which identifies the exact recording (BPM only).
Nothing is guessed: a value no source has is left empty for the DJ app to
analyse.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import httpx
import mutagen
import structlog
from mutagen.aiff import AIFF
from mutagen.flac import FLAC
from mutagen.id3 import ID3, TBPM, TKEY, ID3NoHeaderError
from mutagen.mp4 import MP4, MP4FreeForm
from mutagen.wave import WAVE

from .config import DATA_DIR
from .importer import score

logger = structlog.get_logger("gamdl_web.dj")

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aif", ".aiff", ".wav", ".flac", ".alac", ".mp4"}
CACHE_PATH = DATA_DIR / "dj_cache.json"
GETSONGBPM_URL = "https://api.getsong.co"
DEEZER_URL = "https://api.deezer.com"
NOTATIONS = ["camelot", "musical", "open"]

# ---- key notation ----------------------------------------------------------

PITCHES = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
SHARP_TO_FLAT = {"C#": "Db", "D#": "Eb", "G#": "Ab", "A#": "Bb", "Gb": "F#", "Cb": "B", "Fb": "E", "E#": "F", "B#": "C"}
# Camelot number for (pitch class, minor?)
CAMELOT_MINOR = {8: 1, 3: 2, 10: 3, 5: 4, 0: 5, 7: 6, 2: 7, 9: 8, 4: 9, 11: 10, 6: 11, 1: 12}
CAMELOT_MAJOR = {11: 1, 6: 2, 1: 3, 8: 4, 3: 5, 10: 6, 5: 7, 0: 8, 7: 9, 2: 10, 9: 11, 4: 12}


def parse_key(text: str | None) -> tuple[int, bool] | None:
    """(pitch class 0-11, minor) from "8A", "Am", "A minor", "A♭m", "1m"/"1d" (Open Key)."""
    if not text:
        return None
    t = str(text).strip().replace("♯", "#").replace("♭", "b")
    m = re.fullmatch(r"0?(\d{1,2})\s*([AaBb])", t)
    if m and 1 <= int(m[1]) <= 12:
        n, minor = int(m[1]), m[2].upper() == "A"
        table = CAMELOT_MINOR if minor else CAMELOT_MAJOR
        return next(pc for pc, num in table.items() if num == n), minor
    m = re.fullmatch(r"0?(\d{1,2})\s*([mMdD])", t)
    if m and 1 <= int(m[1]) <= 12:
        # Open Key: 1d = C major, 1m = A minor, going up in fifths.
        n, minor = int(m[1]), m[2].lower() == "m"
        pc = ((n - 1) * 7 + (9 if minor else 0)) % 12
        return pc, minor
    m = re.fullmatch(r"([A-Ga-g])\s*([#b]?)\s*(m|min|minor|maj|major|M)?\.?", t)
    if not m:
        return None
    name = m[1].upper() + (m[2] or "")
    name = SHARP_TO_FLAT.get(name, name)
    if name not in PITCHES:
        return None
    return PITCHES.index(name), (m[3] or "").lower() in {"m", "min", "minor"}


def format_key(key: tuple[int, bool], notation: str) -> str:
    pc, minor = key
    if notation == "musical":
        return PITCHES[pc] + ("m" if minor else "")
    if notation == "open":
        n = ((pc - (9 if minor else 0)) * 7) % 12 + 1
        return f"{n}{'m' if minor else 'd'}"
    return f"{(CAMELOT_MINOR if minor else CAMELOT_MAJOR)[pc]}{'A' if minor else 'B'}"


def parse_bpm(value: Any) -> float | None:
    try:
        bpm = float(str(value).strip().split()[0].replace(",", "."))
    except (ValueError, IndexError):
        return None
    return round(bpm, 2) if 40 <= bpm <= 260 else None


# ---- reading and writing tags ------------------------------------------------

def read_tags(path: str) -> dict[str, Any]:
    """Title, artist, length, BPM and key from any audio file mutagen reads."""
    out: dict[str, Any] = {"title": None, "artist": None, "length": None, "bpm": None, "key": None}
    try:
        audio = mutagen.File(path)
    except Exception:
        return out
    if audio is None:
        return out
    out["length"] = getattr(audio.info, "length", None)
    tags = audio.tags or {}
    if isinstance(audio, MP4):
        get = lambda k: (tags.get(k) or [None])[0]
        out["title"], out["artist"] = get("©nam"), get("©ART")
        out["bpm"] = parse_bpm(get("tmpo"))
        raw = get("----:com.apple.iTunes:initialkey") or get("----:com.apple.iTunes:KEY")
        out["key"] = raw.decode(errors="ignore") if isinstance(raw, bytes) else raw
    elif hasattr(tags, "getall"):  # ID3: MP3, AIFF, WAV
        text = lambda k: str(tags[k].text[0]) if k in tags and tags[k].text else None
        out["title"], out["artist"] = text("TIT2"), text("TPE1")
        out["bpm"] = parse_bpm(text("TBPM"))
        out["key"] = text("TKEY")
    else:  # Vorbis comments: FLAC, Ogg
        get = lambda k: (tags.get(k) or tags.get(k.lower()) or [None])[0]
        out["title"], out["artist"] = get("TITLE"), get("ARTIST")
        out["bpm"] = parse_bpm(get("BPM"))
        out["key"] = get("INITIALKEY") or get("KEY")
    return out


def write_tags(path: str, bpm: float | None, key: str | None) -> None:
    """Write BPM and key where rekordbox, Serato and Traktor look for them."""
    suffix = Path(path).suffix.lower()
    if suffix in {".m4a", ".mp4", ".alac"}:
        audio = MP4(path)
        if bpm:
            audio["tmpo"] = [int(round(bpm))]
        if key:
            audio["----:com.apple.iTunes:initialkey"] = [MP4FreeForm(key.encode())]
        audio.save()
    elif suffix == ".flac":
        audio = FLAC(path)
        if bpm:
            audio["BPM"] = [f"{bpm:g}"]
        if key:
            audio["INITIALKEY"] = [key]
        audio.save()
    else:
        audio = {".mp3": None, ".wav": WAVE, ".aif": AIFF, ".aiff": AIFF}.get(suffix, None)
        if suffix == ".mp3":
            try:
                tags = ID3(path)
            except ID3NoHeaderError:
                tags = ID3()
            if bpm:
                tags.setall("TBPM", [TBPM(encoding=3, text=[f"{round(bpm)}"])])
            if key:
                tags.setall("TKEY", [TKEY(encoding=3, text=[key])])
            tags.save(path, v2_version=3)
        elif audio is not None:
            f = audio(path)
            if f.tags is None:
                f.add_tags()
            if bpm:
                f.tags.setall("TBPM", [TBPM(encoding=3, text=[f"{round(bpm)}"])])
            if key:
                f.tags.setall("TKEY", [TKEY(encoding=3, text=[key])])
            f.save()


# ---- sources -----------------------------------------------------------------

class ReferenceFolder:
    """The user's existing files, indexed once, for copying their key/BPM."""

    def __init__(self, folder: str) -> None:
        self.entries: list[dict] = []
        root = Path(folder).expanduser()
        if not root.is_dir():
            return
        for path in root.rglob("*"):
            if path.suffix.lower() in AUDIO_EXTENSIONS and path.is_file() and not path.name.startswith("._"):
                tags = read_tags(str(path))
                if tags["bpm"] or tags["key"]:
                    tags["title"] = tags["title"] or re.sub(r"^\d+(-\d+)?\s*", "", path.stem)
                    tags["path"] = str(path)
                    self.entries.append(tags)

    def find(self, title: str, artist: str | None, length: float | None) -> dict | None:
        best, best_score = None, 0.0
        for e in self.entries:
            s = score(e.get("artist") or "", e["title"], {"name": title, "artist": artist or ""})
            # Length tells edits apart (Extended Mix vs Radio Edit), and a near-identical
            # length backs up a match when the user's tags are in Korean and Apple's in English.
            if length and e.get("length"):
                gap = abs(length - e["length"])
                s += 0.25 if gap <= 2 else (-0.3 if gap > 4 else 0)
            if s > best_score:
                best, best_score = e, s
        return best if best_score >= 0.8 else None


class Lookup:
    """GetSongBPM and Deezer, with a cache so repeat downloads cost nothing."""

    def __init__(self, getsongbpm_key: str = "") -> None:
        self.key = (getsongbpm_key or "").strip()
        self.client = httpx.AsyncClient(timeout=15, headers={"User-Agent": "PappleMusic (+https://github.com/lewisysh/papple-music)"})
        try:
            self.cache = json.loads(CACHE_PATH.read_text())
        except (OSError, ValueError):
            self.cache = {}

    async def close(self) -> None:
        await self.client.aclose()
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(self.cache, ensure_ascii=False))

    async def getsongbpm(self, song_id: str, title: str, artist: str | None) -> dict | None:
        if not self.key:
            return None
        cache_key = f"gsb:{song_id}"
        if cache_key in self.cache and time.time() - self.cache[cache_key]["at"] < 30 * 86400:
            return self.cache[cache_key]["data"]
        lookup = f"song:{title} artist:{artist}" if artist else f"song:{title}"
        r = await self.client.get(f"{GETSONGBPM_URL}/search/", params={
            "api_key": self.key, "type": "both" if artist else "song", "lookup": lookup, "limit": 10,
        })
        if r.status_code in {401, 403}:
            raise ValueError("GetSongBPM API 키가 올바르지 않습니다")
        r.raise_for_status()
        results = r.json().get("search")
        found = None
        if isinstance(results, list):
            best = 0.0
            for item in results:
                s = score(artist or "", title, {"name": item.get("title"), "artist": (item.get("artist") or {}).get("name")})
                if s > best and (item.get("tempo") or item.get("key_of")):
                    best, found = s, item
            if best < 0.8:
                found = None
        data = found and {"bpm": parse_bpm(found.get("tempo")), "key": found.get("key_of"), "url": found.get("uri")}
        self.cache[cache_key] = {"at": time.time(), "data": data}
        return data

    async def deezer_bpm(self, isrc: str | None) -> float | None:
        if not isrc:
            return None
        cache_key = f"dz:{isrc}"
        if cache_key not in self.cache:
            r = await self.client.get(f"{DEEZER_URL}/track/isrc:{isrc}")
            data = r.json() if r.status_code == 200 else {}
            self.cache[cache_key] = {"at": time.time(), "data": parse_bpm(data.get("bpm"))}
        return self.cache[cache_key]["data"]


async def tag_track(path: str, *, song_id: str, title: str, artist: str | None, isrc: str | None,
                    reference: ReferenceFolder | None, lookup: Lookup, notation: str) -> dict[str, Any]:
    """Find key/BPM for one downloaded song and write them; returns what was used."""
    length = read_tags(path).get("length")
    bpm = key = None
    sources: list[str] = []
    if reference:
        hit = reference.find(title, artist, length)
        if hit:
            bpm, key = hit["bpm"], hit["key"]
            sources.append("file")
    if not (bpm and key):
        try:
            gsb = await lookup.getsongbpm(song_id, title, artist)
        except (httpx.HTTPError, ValueError) as e:
            logger.warning(f"GetSongBPM 조회 실패: {e}")
            gsb = None
        if gsb and ((not key and gsb.get("key")) or (not bpm and gsb.get("bpm"))):
            key, bpm = key or gsb.get("key"), bpm or gsb.get("bpm")
            sources.append("getsongbpm")
    if not bpm:
        try:
            bpm = await lookup.deezer_bpm(isrc)
            if bpm:
                sources.append("deezer")
        except httpx.HTTPError:
            pass
    parsed = parse_key(key)
    key_text = format_key(parsed, notation) if parsed else None
    if bpm or key_text:
        write_tags(path, bpm, key_text)
    return {"bpm": bpm, "key": key_text, "sources": sources}
