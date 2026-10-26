"""Import a pasted list of "artist - title" lines: parse it and find each song.

Lists come from anywhere (notes, spreadsheets, tracklist sites), so parsing is
forgiving and matching only trusts a song when the artist, the title and the
version (Extended Mix, a remix, ...) all line up.
"""

from __future__ import annotations

import csv
import io
import json
import re
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .config import DATA_DIR
from .search import SearchService, _item

IMPORTS_PATH = DATA_DIR / "imports.json"
MAX_LINES = 500

SEPARATORS = re.compile(r"\s+[-–—−]\s+|\t|\s+by\s+", re.I)
LEADING_NOISE = re.compile(r"^\s*(?:\d+\s*[.)\]:-]\s*|\[\d+(?::\d+)+\]\s*|\d+(?::\d+)+\s+|[•·*]\s*)")
TRAILING_TIME = re.compile(r"\s*[\[(]?\d{1,2}:\d{2}(?::\d{2})?[\])]?\s*$")
FEAT = re.compile(r"\s*[\[(]?\s*(?:feat\.?|ft\.?|featuring|with)\s+([^\])]+)[\])]?", re.I)
BRACKETS = re.compile(r"[\[(]([^\])]*)[\])]")
ARTIST_SPLIT = re.compile(r"\s*(?:,|&|\band\b|\bx\b|\bvs\.?|\bfeat\.?|\bft\.?|\bfeaturing\b|\bwith\b|/|;)\s*", re.I)

# Words that make a recording a different version for a DJ.
VERSION_WORDS = {
    "extended", "radio", "edit", "remix", "mix", "vip", "club", "dub", "bootleg", "rework",
    "flip", "instrumental", "acapella", "acappella", "live", "acoustic", "sped", "slowed",
    "nightcore", "karaoke", "version", "intro", "clean", "explicit",
}
# Present in the result but harmless when the list doesn't mention them.
NEUTRAL_WORDS = {"original", "remaster", "remastered", "mono", "stereo", "deluxe", "single", "album", "version", "explicit", "clean"}
# Never what someone means unless they say so.
UNWANTED = re.compile(r"karaoke|tribute|made famous|in the style of|originally performed|instrumental version|cover version|8[- ]?bit|lullaby", re.I)


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").casefold()
    text = text.replace("’", "'").replace("‘", "'")
    text = re.sub(r"[^\w\s']", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _artists(text: str) -> list[str]:
    return [a for a in (_norm(p) for p in ARTIST_SPLIT.split(text or "")) if a]


def _version_words(text: str) -> set[str]:
    words = set()
    for part in BRACKETS.findall(text or ""):
        words |= set(_norm(part).split())
    # "Title - Extended Mix" style suffixes
    if " - " in (text or ""):
        words |= set(_norm(text.split(" - ", 1)[1]).split())
    return words


def _base_title(text: str) -> str:
    text = FEAT.sub("", text or "")
    text = BRACKETS.sub("", text)
    text = text.split(" - ", 1)[0]
    return _norm(text)


def _clean_line(line: str) -> str:
    line = LEADING_NOISE.sub("", line.strip())
    line = TRAILING_TIME.sub("", line)
    return line.strip().strip("\"'")


def _from_csv(text: str) -> list[dict] | None:
    """Spreadsheet exports with an artist column and a title column."""
    first = text.lstrip().split("\n", 1)[0].lower()
    if not any(d in first for d in (",", "\t", ";")) or not re.search(r"artist|아티스트|가수", first):
        return None
    dialect = csv.Sniffer().sniff(text[:2000], delimiters=",\t;")
    rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    if not rows:
        return None
    keys = {k.lower().strip(): k for k in rows[0] if k}
    artist_key = next((keys[k] for k in keys if re.search(r"artist|아티스트|가수", k)), None)
    title_key = next((keys[k] for k in keys if re.search(r"title|track|song|name|제목|곡", k) and keys[k] != artist_key), None)
    if not artist_key or not title_key:
        return None
    out = []
    for row in rows:
        artist, title = (row.get(artist_key) or "").strip(), (row.get(title_key) or "").strip()
        if title:
            out.append({"line": f"{artist} - {title}" if artist else title, "artist": artist, "title": title})
    return out


def parse(text: str) -> list[dict]:
    """One entry per non-empty line: the raw line plus its best artist/title split."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    entries = _from_csv(text)
    if entries is None:
        entries = []
        for raw in text.split("\n"):
            line = _clean_line(raw)
            if not line or len(line) < 2:
                continue
            parts = [p.strip() for p in SEPARATORS.split(line, maxsplit=1)]
            if len(parts) == 2 and all(parts):
                artist, title = parts
            else:
                artist, title = "", line
            entries.append({"line": line, "artist": artist, "title": title})
    seen, unique = set(), []
    for e in entries:
        key = _norm(e["line"])
        if key and key not in seen:
            seen.add(key)
            unique.append(e)
    return unique[:MAX_LINES]


def score(artist: str, title: str, item: dict) -> float:
    """How well a search result matches the line, 0..1."""
    want_title = _base_title(title)
    got_title = _base_title(item.get("name") or "")
    title_sim = SequenceMatcher(None, want_title, got_title).ratio() if want_title and got_title else 0.0
    if want_title and got_title and (want_title in got_title or got_title in want_title):
        title_sim = max(title_sim, 0.9)

    want_artists = _artists(artist) + [_norm(a) for a in FEAT.findall(title)]
    got_artists = _artists(item.get("artist") or "") + [_norm(a) for a in FEAT.findall(item.get("name") or "")]
    if want_artists:
        best = [max((SequenceMatcher(None, w, g).ratio() for g in got_artists), default=0.0) for w in want_artists]
        artist_sim = best[0] * 0.7 + (sum(best) / len(best)) * 0.3
    else:
        artist_sim = 0.6  # title-only line: can't confirm the artist

    want_v = (_version_words(title) & VERSION_WORDS) - NEUTRAL_WORDS
    got_v = (_version_words(item.get("name") or "") & VERSION_WORDS) - NEUTRAL_WORDS
    # A missing or extra version (VIP, Extended, a remix) is another recording:
    # never "sure", but still offered when the base song matches.
    missing, extra = want_v - got_v, got_v - want_v
    penalty = (0.3 if missing else 0) + (0.2 + 0.05 * (len(extra) - 1) if extra else 0)
    # A remix of a different remixer: the bracket text must match too.
    if want_v and got_v:
        want_br = " ".join(_norm(b) for b in BRACKETS.findall(title))
        got_br = " ".join(_norm(b) for b in BRACKETS.findall(item.get("name") or ""))
        penalty += 0.15 * (1 - SequenceMatcher(None, want_br, got_br).ratio())
    if UNWANTED.search(f"{item.get('name')} {item.get('artist')} {item.get('album')}") and not UNWANTED.search(f"{artist} {title}"):
        penalty += 0.5
    return max(0.0, min(1.0, title_sim * 0.55 + artist_sim * 0.45 - penalty))


# Stores (and languages) whose catalog carries local titles for a script.
LOCAL_STORES = [
    (re.compile(r"[\uac00-\ud7a3\u3131-\u318e]"), [("kr", "ko-KR")]),
    (re.compile(r"[\u3040-\u30ff]"), [("jp", "ja")]),
    (re.compile(r"[\u4e00-\u9fff]"), [("jp", "ja"), ("tw", "zh-Hant-TW")]),
]


async def _local_matches(search: SearchService, artist: str, title: str, candidates: dict[str, dict]) -> None:
    """Lines in Korean/Japanese/Chinese: the account's store may list the song
    under an English title (밤편지 → "Through the Night"). Score against the local
    store's titles and keep the account store's item for the same song id."""
    text = f"{artist} {title}"
    stores = next((s for pattern, s in LOCAL_STORES if pattern.search(text)), None)
    if not stores:
        return
    for storefront, language in stores:
        raw = await search._get(f"/v1/catalog/{storefront}/search", {
            "term": text.strip(), "types": "songs", "limit": 10, "extend": "audioTraits", "l": language,
        })
        local = [_item(r) for r in ((raw.get("results") or {}).get("songs") or {}).get("data", [])]
        hits = sorted(((max(score(artist, title, it), score(title, artist, it) if artist else 0.0), it) for it in local),
                      key=lambda h: h[0], reverse=True)[:3]
        for s, it in hits:
            if s < 0.5 or s <= candidates.get(it["id"], {}).get("score", 0):
                continue
            own = candidates.get(it["id"])
            if own is None:
                data = await search._get(f"/v1/catalog/{{storefront}}/songs/{it['id']}", {"extend": "audioTraits"}, missing_ok=True)
                rows = data.get("data") or []
                if not rows:
                    continue  # not available in the account's store
                own = _item(rows[0])
            candidates[it["id"]] = {**own, "score": round(s, 3), "local_name": it["name"], "local_artist": it["artist"]}
        if any(c["score"] >= 0.82 for c in candidates.values()):
            return


async def match(search: SearchService, artist: str, title: str) -> dict[str, Any]:
    """Search for one line; returns the best candidates and how sure we are."""
    queries = [f"{artist} {title}".strip()]
    if artist:
        queries.append(f"{title} {artist}")  # the line may have been "title - artist"
    candidates: dict[str, dict] = {}
    for i, query in enumerate(queries):
        data = await search.search(query, ["songs"], 10, 0)
        for rank, item in enumerate(data["results"]["songs"]["items"]):
            s = max(score(artist, title, item), score(title, artist, item) if artist else 0.0)
            prev = candidates.get(item["id"])
            if prev is None or s > prev["score"]:
                candidates[item["id"]] = {**item, "score": round(s, 3), "rank": rank + 10 * i}
        best = max((c["score"] for c in candidates.values()), default=0)
        if i == 0 and best >= 0.85:
            break
    if max((c["score"] for c in candidates.values()), default=0) < 0.82:
        await _local_matches(search, artist, title, candidates)
    ranked = sorted(candidates.values(), key=lambda c: c["score"], reverse=True)[:5]
    top = ranked[0]["score"] if ranked else 0
    if ranked and top < 0.5:
        # Names that can't be compared as text (뉴진스 - 하입보이 vs NewJeans - Hype Boy):
        # offer Apple's own best guesses for the user to confirm.
        guesses = sorted(candidates.values(), key=lambda c: c.get("rank", 99))[:3]
        return {"status": "check", "guess": True, "candidates": guesses}
    runner = ranked[1]["score"] if len(ranked) > 1 else 0
    # A near-tie between different recordings is a question for the user.
    if top >= 0.82 and (top - runner >= 0.06 or _same_song(ranked[0], ranked[1])):
        status = "sure"
    elif top >= 0.5:
        status = "check"
    else:
        status = "none"
    return {"status": status, "guess": False, "candidates": ranked}


def _same_song(a: dict, b: dict) -> bool:
    return _norm(a.get("name")) == _norm(b.get("name")) and _norm(a.get("artist")) == _norm(b.get("artist"))


# ---- remembered lists ------------------------------------------------------

def _load() -> dict:
    try:
        return json.loads(IMPORTS_PATH.read_text())
    except (OSError, ValueError):
        return {"lists": {}}


def lists() -> list[dict]:
    data = _load()["lists"]
    return sorted(
        ({"name": name, "count": len(v.get("songs", [])), "updated": v.get("updated", 0)} for name, v in data.items()),
        key=lambda x: x["updated"], reverse=True,
    )


def downloaded(name: str) -> list[str]:
    return list(_load()["lists"].get(name, {}).get("songs", []))


def remember(name: str, song_ids: list[str]) -> None:
    data = _load()
    entry = data["lists"].setdefault(name, {"songs": []})
    known = set(entry["songs"])
    entry["songs"] += [s for s in song_ids if s not in known]
    entry["updated"] = time.time()
    IMPORTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = IMPORTS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    tmp.replace(IMPORTS_PATH)


def safe_name(name: str) -> str:
    """A list name usable as a folder name."""
    # Braces too: the name ends up inside a gamdl path template.
    name = re.sub(r'[\\/:*?"<>|{}\x00-\x1f]', " ", name or "").strip(" .")
    return re.sub(r"\s+", " ", name)[:80] or "Imported"


def write_m3u(folder: Path, name: str, paths: list[str]) -> Path | None:
    """An extended M3U8 next to the files, with paths relative to it."""
    files = [Path(p) for p in paths if p and Path(p).is_file()]
    if not files:
        return None
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{name}.m3u8"
    lines = ["#EXTM3U", f"#PLAYLIST:{name}"]
    for f in files:
        try:
            rel = f.relative_to(folder)
        except ValueError:
            rel = f
        lines += [f"#EXTINF:-1,{f.stem}", str(rel)]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target
