"""Songs already on disk, found by the Apple Music ID in their tags.

Downloading again skipped each song only after asking Apple about it (two to
four seconds a song), so a library of 3000 songs took hours just to add five.
This finds them by ID first. Reading tags is cached by path, size and time, so
later runs only read files that are new or changed.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

import mutagen
import structlog

from . import convert, naming
from .config import DATA_DIR

logger = structlog.get_logger("gamdl_web")

CACHE_PATH = DATA_DIR / "known_files.json"
AUDIO_SUFFIXES = {".m4a", ".flac", ".aiff", ".aif", ".wav", ".mp3"}
# Which tag holds the ID: m4a from gamdl, the rest written by convert.py.
ID3_ID = "TXXX:APPLE_MUSICID"


def _first(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return getattr(value, "text", [value])[0] if hasattr(value, "text") else value


def _read(path: str) -> dict[str, Any]:
    """{"id", "title", "artist", "quality", "locked"} of one audio file."""
    audio = mutagen.File(path)
    tags = audio.tags if audio is not None else None
    if not tags:
        return {"id": None}
    suffix = Path(path).suffix.lower()
    if suffix == ".m4a":
        song_id, title, artist = tags.get("cnID"), tags.get("\xa9nam"), tags.get("\xa9ART")
    elif suffix == ".flac":
        song_id, title, artist = tags.get("APPLE_MUSICID"), tags.get("TITLE"), tags.get("ARTIST")
    else:
        song_id, title, artist = tags.get(ID3_ID), tags.get("TIT2"), tags.get("TPE1")
    song_id = _first(song_id)
    if not song_id:
        return {"id": None}
    return {
        "id": str(song_id),
        "title": str(_first(title) or ""),
        "artist": str(_first(artist) or ""),
        "quality": convert.quality_from_info(convert._probe_tags(path)),
        # A locked file from before is downloaded again, not kept.
        "locked": suffix == ".m4a" and convert.is_protected(path),
    }


class KnownFiles:
    def __init__(self, path: Path = CACHE_PATH):
        self.path = path
        self._lock = threading.Lock()
        try:
            self._cache: dict[str, dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._cache = {}

    def scan(self, root: Path, exclude: set[Path] = frozenset()) -> dict[str, list[dict[str, Any]]]:
        """Song ID -> files under root that carry it (folders in exclude left out)."""
        found: dict[str, list[dict[str, Any]]] = {}
        if not root.is_dir():
            return found
        changed = False
        with self._lock:
            seen = set()
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [
                    d for d in dirnames
                    if not d.startswith(".") and Path(dirpath, d) not in exclude
                ]
                for name in filenames:
                    if name.startswith(".") or Path(name).suffix.lower() not in AUDIO_SUFFIXES:
                        continue
                    path = os.path.join(dirpath, name)
                    try:
                        st = os.stat(path)
                    except OSError:
                        continue
                    seen.add(path)
                    entry = self._cache.get(path)
                    if not entry or entry.get("mtime") != st.st_mtime or entry.get("size") != st.st_size:
                        try:
                            info = _read(path)
                        except Exception:
                            # Unreadable (cut short, not audio): never counts as downloaded.
                            info = {"id": None}
                        entry = {"mtime": st.st_mtime, "size": st.st_size, **info}
                        self._cache[path] = entry
                        changed = True
                    if entry.get("id") and not entry.get("locked"):
                        found.setdefault(entry["id"], []).append({"path": path, **entry})
            # Forget files under this root that are gone.
            prefix = str(root).rstrip(os.sep) + os.sep
            for path in [p for p in self._cache if p.startswith(prefix) and p not in seen]:
                del self._cache[path]
                changed = True
            if changed:
                self._save()
        return found

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._cache, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as e:
            logger.debug("known_files_save_failed", error=str(e))


def template_root(output: Path, folder_template: str, values: dict[str, str], sanitize) -> Path:
    """The folder a template always starts with: its leading parts that hold no
    variable, or only the ones given in values (a playlist's name)."""
    parts = []
    for part in folder_template.split("/"):
        if not part or "{" in part:
            break
        names = {m.group(1).lower() for m in naming.VAR_RE.finditer(part)}
        if names - set(values):
            break
        parts.append(sanitize(naming.expand(part, values) if names else part))
    return output.joinpath(*parts)
