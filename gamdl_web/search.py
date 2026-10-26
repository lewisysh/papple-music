from __future__ import annotations

import asyncio
import re
import time
from xml.etree import ElementTree
from pathlib import Path
from typing import Any

import httpx
import structlog
from gamdl.api import AppleMusicApi
from gamdl.api.constants import APPLE_MUSIC_AMP_API_URL, APPLE_MUSIC_SEARCH_API_URI

from .config import Settings, SettingsStore
from .prompts import _artwork
from .runner import SetupError, create_apple_music_api

logger = structlog.get_logger("gamdl_web.search")

ALBUM_IN_URL_RE = re.compile(r"/album/[^/]+/(\d+)")
SEARCH_TYPES = ("songs", "albums", "artists", "playlists", "music-videos")
ANONYMOUS_STOREFRONT = "us"
SESSION_TTL = 20 * 60
# Without an account the session is retried this often, so signing in (wrapper
# login, new cookies) is picked up without waiting for SESSION_TTL.
ANONYMOUS_RETRY = 15
# After the account's token is rate limited (429), catalog reads go through the
# public web-player token for this long; it has its own, separate quota.
THROTTLE_COOLDOWN = 5 * 60


class SearchError(Exception):
    pass


ARTIST_VIEWS = {
    "top-songs": "인기곡",
    "latest-release": "최신 발매",
    "full-albums": "앨범",
    "singles": "싱글 및 EP",
    "live-albums": "라이브 앨범",
    "compilation-albums": "컴필레이션",
    "music-videos": "뮤직비디오",
    "appears-on-albums": "참여한 앨범",
}
ALBUM_VIEWS = {
    "other-versions": "다른 버전",
    "related-videos": "뮤직비디오",
    "more-by-artist": "{artist}의 다른 앨범",
    "you-might-also-like": "비슷한 앨범",
    "appears-on": "수록된 플레이리스트",
}
BROWSE_TTL = 60 * 60
TAG_RE = re.compile(r"<[^>]+>")
BR_RE = re.compile(r"<br\s*/?>", re.I)


TTML_NS = "{http://www.w3.org/ns/ttml}"


def _ttml_time(value: str | None) -> float | None:
    if not value:
        return None
    seconds = 0.0
    for part in value.rstrip("s").split(":"):
        seconds = seconds * 60 + float(part)
    return seconds


def parse_ttml(ttml: str) -> list[dict]:
    """Line-timed lyrics from Apple's TTML: [{start, end, text}] (start None if unsynced)."""
    try:
        root = ElementTree.fromstring(ttml)
    except ElementTree.ParseError:
        return []
    lines = []
    for p in root.iter(f"{TTML_NS}p"):
        text = "".join(p.itertext()).strip()
        if text:
            lines.append({"start": _ttml_time(p.get("begin")), "end": _ttml_time(p.get("end")), "text": text})
    return lines


def _text(notes: Any) -> str | None:
    if isinstance(notes, dict):
        notes = notes.get("standard") or notes.get("short")
    if not notes:
        return None
    # Keep Apple's paragraph breaks; drop the rest of the markup.
    return TAG_RE.sub("", BR_RE.sub("\n", notes)).strip()


def _artists(relationships: dict) -> list[dict]:
    return [
        {"id": a["id"], "name": (a.get("attributes") or {}).get("name")}
        for a in (relationships.get("artists") or {}).get("data", [])
    ]


def _detail(raw: dict) -> dict[str, Any]:
    """An item plus the fields a detail page shows."""
    attributes = raw.get("attributes") or {}
    item = _item(raw)
    item["artwork"] = _artwork(attributes, 600)
    artwork = attributes.get("artwork") or {}
    item.update(
        colors={k: artwork.get(k) for k in ("bgColor", "textColor1", "textColor2", "textColor3", "textColor4")},
        digital_master=attributes.get("isMasteredForItunes"),
        motion=bool(attributes.get("editorialVideo")),
        label=attributes.get("recordLabel"),
        copyright=attributes.get("copyright"),
        genres=attributes.get("genreNames") or [],
        single=attributes.get("isSingle"),
        compilation=attributes.get("isCompilation"),
        description=_text(attributes.get("editorialNotes")) or _text(attributes.get("description"))
        or _text(attributes.get("artistBio")),
        origin=attributes.get("origin"),
        born=attributes.get("bornOrFormed"),
        modified=attributes.get("lastModifiedDate"),
    )
    return item


def _item(raw: dict) -> dict[str, Any]:
    attributes = raw.get("attributes") or {}
    kind = raw.get("type")
    item = {
        "id": raw.get("id"),
        "type": kind,
        "name": attributes.get("name"),
        "artist": attributes.get("artistName") or attributes.get("curatorName"),
        "album": attributes.get("albumName"),
        "artwork": _artwork(attributes, 120 if kind == "songs" else 400),
        "url": attributes.get("url"),
        "duration": attributes.get("durationInMillis"),
        "release": attributes.get("releaseDate"),
        "tracks": attributes.get("trackCount"),
        "explicit": attributes.get("contentRating") == "explicit",
        "traits": attributes.get("audioTraits") or [],
        "genre": (attributes.get("genreNames") or [None])[0],
        "disc": attributes.get("discNumber"),
        "number": attributes.get("trackNumber"),
    }
    if kind in {"songs", "music-videos"} and item["url"]:
        # Song links look like /album/<slug>/<album id>?i=<song id>.
        match = ALBUM_IN_URL_RE.search(item["url"])
        item["album_id"] = match[1] if match else None
    if kind == "music-videos":
        item["traits"] = [t for t, on in (("4k", attributes.get("has4K")), ("hdr", attributes.get("hasHDR"))) if on]
        url = (attributes.get("artwork") or {}).get("url")
        item["artwork"] = url and url.replace("{w}", "640").replace("{h}", "360").replace("{f}", "jpg")
        # Apple's preview stream: plain HLS, about 30 seconds, playable right away.
        item["preview_hls"] = next((p.get("hlsUrl") for p in attributes.get("previews") or [] if p.get("hlsUrl")), None)
    return item


class SearchService:
    """Apple Music catalog search with one reusable API session."""

    def __init__(self, store: SettingsStore) -> None:
        self.store = store
        self._api: AppleMusicApi | None = None
        # gamdl's own client retries 429/5xx with backoff for up to a minute;
        # an interactive search should answer fast instead.
        self._client: httpx.AsyncClient | None = None
        self._key: tuple | None = None
        self._created = 0.0
        self._suggest_cache: dict[str, dict[str, Any]] = {}
        self._anonymous = False
        self._web: httpx.AsyncClient | None = None
        self._web_created = 0.0
        self._throttled_until = 0.0
        self._browse: tuple[float, list] | None = None
        self._lock = asyncio.Lock()

    @staticmethod
    def _session_key(settings: Settings) -> tuple:
        cookies = Path(settings.cookies_path).expanduser()
        return (
            settings.use_wrapper,
            settings.wrapper_url,
            settings.language,
            cookies.stat().st_mtime if cookies.is_file() else None,
        )

    async def _session(self, fresh: bool = False) -> AppleMusicApi:
        async with self._lock:
            settings = self.store.get()
            key = self._session_key(settings)
            if (
                not fresh
                and self._api is not None
                and key == self._key
                and time.time() - self._created < (ANONYMOUS_RETRY if self._anonymous else SESSION_TTL)
            ):
                return self._api
            await self._close_api()
            try:
                api, wrapper_api = await create_apple_music_api(settings)
                if wrapper_api:
                    await wrapper_api.client.aclose()
                self._anonymous = False
            except SetupError as e:
                # Searching the catalog needs no account; downloads still will.
                logger.info(f"계정 없이 검색합니다: {e}")
                api = await AppleMusicApi.create(
                    storefront=ANONYMOUS_STOREFRONT, language=settings.language
                )
                self._anonymous = True
            self._api, self._key, self._created = api, key, time.time()
            self._client = httpx.AsyncClient(headers=dict(api.client.headers), timeout=15)
            return api

    async def suggest(self, term: str) -> dict[str, Any]:
        """Type-ahead: suggested search terms plus top matches, like the Music app."""
        key = term.casefold()
        if key in self._suggest_cache:
            return self._suggest_cache[key]
        raw = await self._get(
            "/v1/catalog/{storefront}/search/suggestions",
            {
                "term": term,
                "kinds": "terms,topResults",
                "types": "songs,artists,albums,playlists,music-videos",
                "limit": 10,
                "l": self.store.get().language,
            },
        )
        terms, items = [], []
        for suggestion in (raw.get("results") or {}).get("suggestions") or []:
            if suggestion.get("kind") == "terms" and suggestion.get("searchTerm"):
                terms.append(suggestion["searchTerm"])
            elif suggestion.get("kind") == "topResults" and suggestion.get("content"):
                items.append(_item(suggestion["content"]))
        result = {"term": term, "terms": terms[:4], "items": items[:6]}
        if len(self._suggest_cache) >= 300:
            self._suggest_cache.pop(next(iter(self._suggest_cache)))
        self._suggest_cache[key] = result
        return result

    async def search(
        self, term: str, types: list[str], limit: int, offset: int, top: bool = False
    ) -> dict[str, Any]:
        params = {
            "term": term,
            "types": ",".join(types),
            "limit": limit,
            "offset": offset,
            "extend": "audioTraits",
            "l": self.store.get().language,
        }
        if top:
            # Apple's "Top Results" shelf: mixed types ranked by relevance.
            params["with"] = "topResults"
        raw = await self._get(APPLE_MUSIC_SEARCH_API_URI, params)
        api = self._api
        results = raw.get("results") or {}
        order = (raw.get("meta") or {}).get("results", {}).get("order") or list(results)
        return {
            "term": term,
            "storefront": api.storefront,
            "anonymous": self._anonymous,
            "order": [t for t in order if t in types],
            "top": [_item(r) for r in (results.get("topResults") or {}).get("data", [])],
            "results": {
                kind: {
                    "items": [_item(r) for r in (results.get(kind) or {}).get("data", [])],
                    "next": bool((results.get(kind) or {}).get("next")),
                }
                for kind in types
            },
        }

    async def _web_client(self) -> httpx.AsyncClient:
        """A client on the public web-player token (no account), for catalog reads."""
        if self._web is None or time.time() - self._web_created > SESSION_TTL:
            api = await AppleMusicApi.create(storefront=ANONYMOUS_STOREFRONT, language=self.store.get().language)
            headers = dict(api.client.headers)
            await api.client.aclose()
            if self._web is not None:
                await self._web.aclose()
            self._web, self._web_created = httpx.AsyncClient(headers=headers, timeout=15), time.time()
        return self._web

    async def _get(self, uri: str, params: dict | None = None, missing_ok: bool = False) -> dict:
        """GET an AMP API path; "{storefront}" in it is filled from the session."""
        catalog = uri.startswith("/v1/catalog/")
        for attempt in range(2):
            api = await self._session(fresh=attempt > 0)
            url = APPLE_MUSIC_AMP_API_URL + uri.format(storefront=api.storefront)
            # The catalog needs no account, so when the account token is being
            # throttled, read it with the public token instead of failing.
            use_web = catalog and not self._anonymous and time.time() < self._throttled_until
            try:
                client = await self._web_client() if use_web else self._client
                response = await client.get(url, params=params)
                if response.status_code == 429 and catalog and not use_web and not self._anonymous:
                    logger.info("Apple Music이 계정 토큰 요청을 제한해 공용 토큰으로 카탈로그를 읽습니다")
                    self._throttled_until = time.time() + THROTTLE_COOLDOWN
                    response = await (await self._web_client()).get(url, params=params)
            except httpx.HTTPError as e:
                raise SearchError(f"Apple Music에 연결하지 못했습니다 ({type(e).__name__})") from e
            # An expired token shows up as 401/403; rebuild the session once.
            if response.status_code in {401, 403} and not attempt:
                continue
            if response.status_code == 404 and missing_ok:
                return {}
            if response.status_code == 404:
                raise SearchError("Apple Music에서 찾을 수 없습니다")
            if response.status_code == 429:
                raise SearchError("Apple Music 요청이 너무 많습니다. 잠시 후 다시 시도하세요.")
            if response.is_error:
                raise SearchError(f"Apple Music이 HTTP {response.status_code}로 응답했습니다")
            return response.json()
        raise SearchError("Apple Music 인증에 실패했습니다")

    async def album(self, album_id: str) -> dict[str, Any]:
        raw = await self._get(
            f"/v1/catalog/{{storefront}}/albums/{album_id}",
            {
                "include": "tracks,artists",
                "extend": "audioTraits,editorialNotes,editorialVideo",
                "views": ",".join(ALBUM_VIEWS),
                "l": self.store.get().language,
            },
        )
        album = raw["data"][0]
        relationships = album.get("relationships") or {}
        tracks = (relationships.get("tracks") or {}).get("data", [])
        next_uri = (relationships.get("tracks") or {}).get("next")
        while next_uri and len(tracks) < 1000:
            page = await self._get(next_uri.replace("{", "{{").replace("}", "}}"), missing_ok=True)
            tracks += page.get("data", [])
            next_uri = page.get("next")
        detail = _detail(album)
        views = album.get("views") or {}
        return {
            "item": detail,
            "artists": _artists(relationships),
            "tracks": [_item(t) for t in tracks if t.get("attributes")],
            "views": [
                {
                    "key": key,
                    "title": title.format(artist=detail["artist"] or ""),
                    "items": [_item(r) for r in views[key].get("data", []) if r.get("attributes")],
                }
                for key, title in ALBUM_VIEWS.items()
                if views.get(key, {}).get("data")
            ],
        }

    async def motion_master(self, album_id: str) -> str | None:
        raw = await self._get(f"/v1/catalog/{{storefront}}/albums/{album_id}", {"extend": "editorialVideo"})
        video = (raw["data"][0].get("attributes") or {}).get("editorialVideo") or {}
        for key in ("motionDetailSquare", "motionSquareVideo1x1"):
            if (video.get(key) or {}).get("video"):
                return video[key]["video"]
        return None

    async def browse(self) -> list[dict]:
        if self._browse and time.time() - self._browse[0] < BROWSE_TTL:
            return self._browse[1]
        raw = await self._get(
            "/v1/recommendations/{storefront}",
            {"name": "search-landing", "platform": "web", "extend": "editorialArtwork", "l": self.store.get().language},
        )
        tiles = []
        for rec in raw.get("data", []):
            for it in (rec.get("relationships") or {}).get("contents", {}).get("data", []):
                a = it.get("attributes") or {}
                art = (a.get("editorialArtwork") or {}).get("subscriptionCover") or a.get("artwork") or {}
                name = a.get("shortName") or a.get("name") or (a.get("editorialNotes") or {}).get("name") or art.get("alt")
                if not name or not art.get("url"):
                    continue
                tiles.append({
                    "id": it["id"],
                    "type": it["type"],
                    "name": name,
                    "image": art["url"].replace("{w}", "1200").replace("{h}", "300").replace("{f}", "jpg").replace("{c}", "bb"),
                    "color": art.get("bgColor"),
                    "url": a.get("url"),
                })
        self._browse = (time.time(), tiles)
        return tiles

    async def curator(self, curator_id: str) -> dict[str, Any]:
        raw = await self._get(
            f"/v1/catalog/{{storefront}}/apple-curators/{curator_id}",
            {"include": "playlists", "extend": "editorialArtwork", "l": self.store.get().language},
        )
        curator = raw["data"][0]
        attributes = curator.get("attributes") or {}
        item = _detail(curator)
        item["name"] = attributes.get("shortName") or attributes.get("name")
        item["type"] = "curators"
        playlists = ((curator.get("relationships") or {}).get("playlists") or {}).get("data", [])
        return {"item": item, "playlists": [_item(p) for p in playlists if p.get("attributes")]}

    async def preview(self, url: str) -> dict[str, Any] | None:
        """Title, artist and artwork for an Apple Music link, for a queued download."""
        from gamdl.interface import AppleMusicInterface

        info = AppleMusicInterface.get_url_info(url)
        if not info or not info.id or info.library_id:
            return None
        kind, item_id = ("songs", info.sub_id) if info.sub_id else (
            {"album": "albums", "playlist": "playlists", "song": "songs", "music-video": "music-videos", "artist": "artists"}.get(info.type), info.id)
        if not kind:
            return None
        raw = await self._get(f"/v1/catalog/{{storefront}}/{kind}/{item_id}", {"l": self.store.get().language}, missing_ok=True)
        data = (raw.get("data") or [{}])[0]
        a = data.get("attributes") or {}
        if not a.get("name"):
            return None
        return {
            "title": a["name"],
            "artist": a.get("artistName") or a.get("curatorName"),
            "artwork": _artwork(a, 300) if (a.get("artwork") or {}).get("url") else None,
            "type": kind,
        }

    async def refresh_account(self) -> None:
        """Retry signing in now if the session was built without an account."""
        if self._anonymous or self._api is None:
            await self._session(fresh=True)

    async def profile(self) -> dict[str, Any] | None:
        await self._session()
        if self._anonymous:
            return None
        raw = await self._get("/v1/me/social/profile", missing_ok=True)
        data = (raw.get("data") or [{}])[0].get("attributes") or {}
        if not data:
            return None
        artwork = (data.get("artwork") or {}).get("url")
        return {
            "name": data.get("name"),
            "handle": data.get("handle"),
            "url": data.get("url"),
            "avatar": artwork and artwork.replace("{w}", "96").replace("{h}", "96").replace("{c}", "cc").replace("{f}", "jpg"),
        }

    async def library_playlists(self) -> list[dict]:
        await self._session()
        if self._anonymous:
            return []
        playlists, offset = [], 0
        while offset < 500:
            raw = await self._get("/v1/me/library/playlists", {"limit": 100, "offset": offset}, missing_ok=True)
            page = raw.get("data", [])
            for p in page:
                a = p.get("attributes") or {}
                playlists.append({
                    "id": p["id"],
                    "name": a.get("name"),
                    "editable": bool(a.get("canEdit")),
                    "artwork": _artwork(a, 96) if (a.get("artwork") or {}).get("url") else None,
                })
            if not raw.get("next"):
                break
            offset += len(page)
        return playlists

    async def library_playlist(self, playlist_id: str) -> dict[str, Any]:
        raw = await self._get(f"/v1/me/library/playlists/{playlist_id}", {"l": self.store.get().language})
        playlist = raw["data"][0]
        attributes = playlist.get("attributes") or {}
        tracks, offset = [], 0
        while offset < 2000:
            page = await self._get(
                f"/v1/me/library/playlists/{playlist_id}/tracks",
                {"include": "catalog", "extend": "audioTraits", "limit": 100, "offset": offset},
                missing_ok=True,
            )
            data = page.get("data", [])
            for t in data:
                catalog = ((t.get("relationships") or {}).get("catalog") or {}).get("data") or []
                # Download the catalog version when there is one; the library entry otherwise.
                item = _item(catalog[0]) if catalog and catalog[0].get("attributes") else _item(t)
                if not catalog:
                    item["url"] = None
                tracks.append(item)
            if not page.get("next"):
                break
            offset += len(data)
        item = _detail(playlist)
        item.update(
            type="library-playlists",
            artist="내 보관함",
            artwork=_artwork(attributes, 600),
            url=f"https://music.apple.com/library/playlist/{playlist_id}",
        )
        return {"item": item, "tracks": tracks}

    async def playlist(self, playlist_id: str) -> dict[str, Any]:
        language = self.store.get().language
        raw = await self._get(
            f"/v1/catalog/{{storefront}}/playlists/{playlist_id}",
            {"include": "tracks", "extend": "audioTraits,editorialNotes", "l": language},
        )
        playlist = raw["data"][0]
        tracks = ((playlist.get("relationships") or {}).get("tracks") or {}).get("data", [])
        # The include returns the first 100; the rest come from the tracks endpoint.
        while len(tracks) % 100 == 0 and 0 < len(tracks) < 1000:
            page = await self._get(
                f"/v1/catalog/{{storefront}}/playlists/{playlist_id}/tracks",
                {"offset": len(tracks), "limit": 100, "extend": "audioTraits", "l": language},
                missing_ok=True,
            )
            if not page.get("data"):
                break
            tracks += page["data"]
        return {
            "item": _detail(playlist),
            "tracks": [_item(t) for t in tracks if t.get("attributes")],
        }

    async def artist(self, artist_id: str) -> dict[str, Any]:
        raw = await self._get(
            f"/v1/catalog/{{storefront}}/artists/{artist_id}",
            {
                "views": ",".join(ARTIST_VIEWS),
                "extend": "artistBio,origin,bornOrFormed",
                "l": self.store.get().language,
            },
        )
        artist = raw["data"][0]
        views = artist.get("views") or {}
        return {
            "item": _detail(artist),
            "views": [
                {
                    "key": key,
                    "title": ARTIST_VIEWS[key],
                    "items": [_item(r) for r in views[key].get("data", []) if r.get("attributes")],
                    "next": bool(views[key].get("next")),
                }
                for key in ARTIST_VIEWS
                if views.get(key, {}).get("data")
            ],
        }

    async def artist_view(self, artist_id: str, view: str, offset: int) -> dict[str, Any]:
        raw = await self._get(
            f"/v1/catalog/{{storefront}}/artists/{artist_id}/view/{view}",
            {"offset": offset, "limit": 100, "extend": "audioTraits", "l": self.store.get().language},
        )
        return {"items": [_item(r) for r in raw.get("data", []) if r.get("attributes")], "next": bool(raw.get("next"))}

    async def song(self, song_id: str) -> dict[str, Any]:
        """Song details plus its time-synced lyrics, for the info sheet and lyrics view."""
        raw = await self._get(
            f"/v1/catalog/{{storefront}}/songs/{song_id}",
            {"include": "lyrics,albums,artists", "extend": "audioTraits", "l": self.store.get().language},
        )
        song = raw["data"][0]
        attributes = song.get("attributes") or {}
        relationships = song.get("relationships") or {}
        albums = (relationships.get("albums") or {}).get("data") or []
        lyrics = ((relationships.get("lyrics") or {}).get("data") or [{}])[0].get("attributes", {}).get("ttml")
        item = _item(song)
        item.update(
            composer=attributes.get("composerName"),
            genres=attributes.get("genreNames") or [],
            isrc=attributes.get("isrc"),
            album_id=albums[0]["id"] if albums else item.get("album_id"),
            label=(albums[0].get("attributes") or {}).get("recordLabel") if albums else None,
            copyright=(albums[0].get("attributes") or {}).get("copyright") if albums else None,
            digital_master=attributes.get("isAppleDigitalMaster"),
        )
        return {"item": item, "artists": _artists(relationships), "lyrics": parse_ttml(lyrics) if lyrics else []}

    async def post(self, uri: str, body: dict) -> int:
        await self._session()
        response = await self._client.post(
            APPLE_MUSIC_AMP_API_URL + uri.format(storefront=self._api.storefront), json=body
        )
        return response.status_code

    async def warm(self) -> None:
        """Build the session ahead of the first search, which otherwise waits for it."""
        try:
            await self._session()
        except Exception as e:
            logger.info(f"검색 세션을 미리 준비하지 못했습니다: {e}")

    async def _close_api(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        if self._api is not None:
            await self._api.client.aclose()
            self._api = None

    async def close(self) -> None:
        async with self._lock:
            await self._close_api()
            if self._web is not None:
                await self._web.aclose()
                self._web = None
