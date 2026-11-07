from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
import structlog
from gamdl.api import AppleMusicApi, GamdlApiResponseError, WrapperApi
from gamdl.downloader import (
    AppleMusicBaseDownloader,
    AppleMusicDownloader,
    AppleMusicMusicVideoDownloader,
    AppleMusicSongDownloader,
    AppleMusicUploadedVideoDownloader,
)
from gamdl.downloader.enums import DownloadMode, RemuxFormatMusicVideo
from gamdl.interface.types import Cover
from gamdl.interface import (
    AppleMusicBaseInterface,
    AppleMusicInterface,
    AppleMusicMusicVideoInterface,
    AppleMusicSongInterface,
    AppleMusicUploadedVideoInterface,
    ArtistMediaType,
    CoverFormat,
    DrmBackend,
    MusicVideoCodec,
    MusicVideoResolution,
    SongCodec,
    SyncedLyricsFormat,
    UploadedVideoQuality,
)

from . import convert, naming, progress
from .config import Settings
from .prompts import WebPrompts

logger = structlog.get_logger("gamdl_web")


class SetupError(Exception):
    """A problem the user has to fix in settings before anything downloads."""


# The artwork server never upscales: asking for more than the original returns
# the original resolution.
MAX_COVER_SIZE = 10000


# Apple now and then refuses one song's playback request and gives it the
# next time: wait a little and ask again before calling it an error.
PLAYBACK_RETRY_WAITS = (3, 8)


class WebWrapperApi(WrapperApi):
    async def get_playback(self, media_id: str) -> dict:
        for wait in PLAYBACK_RETRY_WAITS:
            try:
                return await super().get_playback(media_id)
            except GamdlApiResponseError as e:
                if e.status_code != 502 or "playback_dispatch_failed" not in str(e.content):
                    raise
                logger.info(f"Apple이 재생 정보를 주지 않아 {wait}초 뒤 다시 요청합니다")
                await asyncio.sleep(wait)
        return await super().get_playback(media_id)


class WebAppleMusicApi(AppleMusicApi):
    """Keeps library songs linked to the catalog past the first page."""

    async def get_extended_api_data(self, next_uri: str | None, href_uri: str) -> dict:
        # A library playlist's "next" link drops include=catalog, so songs past
        # the first 100 lost their catalog link and gamdl saved the library's
        # still-encrypted file as if it were DRM-free.
        if next_uri and urlparse(next_uri).path.startswith("/v1/me/library/") and "include=" not in next_uri:
            next_uri += ("&" if "?" in next_uri else "?") + "include=catalog"
        return await super().get_extended_api_data(next_uri, href_uri)


class WebBaseInterface(AppleMusicBaseInterface):
    """Raw covers via the thumbnail server, and cover errors no longer fail a track."""

    def _get_raw_cover_url(self, cover_url_template: str) -> str:
        # gamdl's raw URLs (a1.mzstatic.com originals) now answer 403.
        original_name = cover_url_template.rsplit("/", 2)[-2]
        extension = original_name.rsplit(".", 1)[-1].lower()
        extension = {"jpg": "jpg", "jpeg": "jpg", "png": "png"}.get(extension, "png")
        return re.sub(
            r"/\{w\}x\{h\}[^/]*$",
            f"/{MAX_COVER_SIZE}x{MAX_COVER_SIZE}bb.{extension}",
            cover_url_template,
        )

    async def get_cover_bytes(self, cover_url: str | None) -> bytes | None:
        progress.report("cover")
        if not cover_url:
            return None
        try:
            return await super().get_cover_bytes(cover_url)
        except httpx.HTTPError as e:
            logger.warning(f"커버 이미지를 받지 못해 커버 없이 진행합니다: {e}")
            return None

    async def get_tags_from_asset_info(self, asset_data: dict, *args, **kwargs):
        # The user's own uploads can lack fields gamdl reads without checking,
        # such as an MP3 with no artist.
        name = asset_data.get("itemName") or "Unknown Title"
        defaults = {"artistName": None, "sort-artist": None, "itemName": name, "sort-name": name, "kind": "song", "explicit": 0}
        filled = {**defaults, **{k: v for k, v in asset_data.items() if v is not None}}
        return await super().get_tags_from_asset_info(filled, *args, **kwargs)

    async def get_cover(self, metadata: dict):
        if not ((metadata.get("attributes") or {}).get("artwork") or {}).get("url"):
            # Some songs have no artwork at all, often library songs Apple no longer sells.
            return Cover(file_extension=".jpg")
        cover = await super().get_cover(metadata)
        if cover.file_extension is None:
            # gamdl builds "Cover" + extension later, so keep it a string.
            cover.url = None
            cover.file_extension = ".jpg"
        return cover


async def fetch_in_ranges(url: str, path: str, parts: int = 4) -> None:
    """Download a plain file in a few parallel byte ranges (CDNs cap each connection)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    timeout = httpx.Timeout(20, read=60)
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        async with client.stream("GET", url, headers={"Range": "bytes=0-0"}) as probe:
            probe.raise_for_status()
            match = re.search(r"/(\d+)$", probe.headers.get("content-range", ""))
        if probe.status_code != 206 or not match:
            async with client.stream("GET", url) as r:
                r.raise_for_status()
                with target.open("wb") as f:
                    async for chunk in r.aiter_bytes(1 << 16):
                        f.write(chunk)
            return
        size = int(match.group(1))
        step = -(-size // parts)
        with target.open("wb") as f:
            f.truncate(size)

        async def fetch(start: int) -> None:
            end = min(size, start + step) - 1
            async with client.stream("GET", url, headers={"Range": f"bytes={start}-{end}"}) as r:
                r.raise_for_status()
                if r.status_code != 206:
                    raise ValueError("range request ignored")
                with target.open("r+b") as f:
                    f.seek(start)
                    async for chunk in r.aiter_bytes(1 << 16):
                        f.write(chunk)
                    if f.tell() != end + 1:
                        raise ValueError("short range")

        await asyncio.gather(*(fetch(start) for start in range(0, size, step)))


# Leaves room under the 255-byte limit for a converted file's longer extension.
MAX_NAME_BYTES = 240


class WebBaseDownloader(AppleMusicBaseDownloader):
    """Adds a separate path for playlist tracks and honours "cover" in exclude_tags."""

    _TEMPLATE_ATTRS = (
        "album_folder_template",
        "compilation_folder_template",
        "no_album_folder_template",
        "single_disc_file_template",
        "multi_disc_file_template",
        "no_album_file_template",
    )

    def __init__(
        self,
        *args,
        playlist_track_template: str | None = None,
        single_song_template: str | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.playlist_track_template = playlist_track_template
        self.single_song_template = single_song_template
        # Set by the job while it downloads a link to one song.
        self.single_song_mode = False
        # A song's place in a pasted list, for %position%; set by the job per link.
        self.list_position: int | None = None
        self.list_total: int | None = None
        # The item being named, so %isrc%, %label% and %upc% can be read from it.
        self.current_media = None
        # Playback cache files need no tags; StreamService turns this on.
        self.skip_tags = False

    def _sanitize_string(self, dirty_string: str, file_ext: str | None = None) -> str:
        # macOS and most disks allow 255 bytes per name, and Korean takes 3 per
        # letter: a credit listing dozens of artists made the folder fail.
        clean = super()._sanitize_string(dirty_string, file_ext)
        if len(clean.encode()) <= MAX_NAME_BYTES:
            return clean
        ext = file_ext if file_ext and clean.endswith(file_ext) else ""
        stem = clean[: len(clean) - len(ext)]
        room = MAX_NAME_BYTES - len(ext.encode()) - len("…".encode())
        return stem.encode()[:room].decode(errors="ignore").rstrip(" .,&") + "…" + ext

    def get_final_path(self, tags, file_extension, playlist_tags):
        if self.playlist_track_template and playlist_tags and playlist_tags.title:
            override = self.playlist_track_template
        elif self.single_song_mode and self.single_song_template and file_extension == ".m4a":
            override = self.single_song_template
        else:
            override = None

        templates = {attr: getattr(self, attr) for attr in self._TEMPLATE_ATTRS}
        if override is not None:
            # Point every template at the chosen one for this call.
            folder, _, file = override.rpartition("/")
            chosen = {attr: folder if attr.endswith("folder_template") else file for attr in templates}
        else:
            chosen = dict(templates)
        if any("%" in t for t in chosen.values()):
            values = naming.context(
                tags, playlist_tags, self.current_media, self.list_position, self.list_total
            )
            chosen = {attr: naming.expand(t, values) for attr, t in chosen.items()}
        if chosen == templates:
            return super().get_final_path(tags, file_extension, playlist_tags)

        # Reuse gamdl's formatting and cleanup with the filled-in templates;
        # nothing awaits in between, so no other item sees them.
        for attr, value in chosen.items():
            setattr(self, attr, value)
        try:
            return super().get_final_path(tags, file_extension, playlist_tags)
        finally:
            for attr, value in templates.items():
                setattr(self, attr, value)

    def get_playlist_file_path(self, tags):
        saved = self.playlist_folder_template, self.playlist_file_template
        if "%" in saved[0] + saved[1]:
            values = {
                "playlist": tags.title or "", "playlistartist": tags.artist or "",
                "playlist_id": str(tags.playlist_id or ""),
            }
            self.playlist_folder_template = naming.expand(saved[0], values)
            self.playlist_file_template = naming.expand(saved[1], values)
        try:
            return super().get_playlist_file_path(tags)
        finally:
            self.playlist_folder_template, self.playlist_file_template = saved

    async def download_stream(self, stream_url: str, download_path: str):
        if self.skip_tags and not stream_url.split("?")[0].endswith(".m3u8"):
            # Playback cache: fetch in-process in parallel ranges instead of
            # starting a yt-dlp process; fall back to it if the CDN won't play along.
            try:
                await fetch_in_ranges(stream_url, download_path)
                return
            except (httpx.HTTPError, OSError, ValueError) as e:
                logger.debug("range_fetch_failed", error=str(e))
                Path(download_path).unlink(missing_ok=True)
        total = await progress.stream_size(stream_url)
        watcher = asyncio.create_task(progress.watch(download_path, total))
        try:
            await super().download_stream(stream_url, download_path)
        finally:
            watcher.cancel()
        progress.report("download", total, total)
        if not stream_url.split("?")[0].endswith(".m3u8"):
            await self._to_mp4(download_path)

    async def _to_mp4(self, path: str) -> None:
        """A library upload can be an MP3 or the like; gamdl only writes MP4.
        AAC and ALAC move into MP4 as they are, anything else becomes AAC 256."""
        with open(path, "rb") as f:
            if f.read(8)[4:8] == b"ftyp":
                return
        codec = (await convert.probe(path, convert._ffprobe_for(self.ffmpeg_path))).get("codec_name")
        audio = ["-c:a", "copy"] if codec in {"aac", "alac"} else ["-c:a", "aac", "-b:a", "256k"]
        out = f"{path}.mp4"
        proc = await asyncio.create_subprocess_exec(
            self.ffmpeg_path, "-v", "error", "-y", "-i", path, "-map", "0:a:0", *audio, "-f", "mp4", out,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            Path(out).unlink(missing_ok=True)
            raise RuntimeError(f"올린 파일을 m4a로 옮기지 못했습니다 ({codec}): {err.decode(errors='replace')[-200:]}")
        os.replace(out, path)
        if codec not in {"aac", "alac"}:
            logger.info(f"올린 파일이 {codec}라서 AAC 256kbps m4a로 바꿨습니다")

    async def apply_tags(self, media_path, tags, cover_bytes):
        if self.skip_tags:
            return
        progress.report("tags")
        if "cover" in (self.exclude_tags or []):
            cover_bytes = None
        await super().apply_tags(media_path, tags, cover_bytes)


LOCKED_LIBRARY_MESSAGE = (
    "Apple Music 카탈로그에서 내려간 보관함 곡이라 잠긴(DRM) 버전만 남아 있어서 받지 않았습니다."
)


class LockedLibrarySongError(Exception):
    """A library song Apple only offers encrypted: it left the catalog."""


async def _is_locked_stream(url: str) -> bool:
    """Whether a library song's stream is still encrypted, from its playlist or
    the first megabyte, so nothing locked is ever saved. Unsure counts as no:
    the job checks the finished file again."""
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            if urlparse(url).path.endswith(".m3u8"):
                text = (await client.get(url)).text
                variant = next((l for l in text.splitlines() if l and not l.startswith("#")), None)
                if "#EXT-X-STREAM-INF" in text and variant:
                    text += (await client.get(urljoin(url, variant))).text
                return any(
                    line.startswith(("#EXT-X-KEY", "#EXT-X-SESSION-KEY")) and "METHOD=NONE" not in line
                    for line in text.splitlines()
                )
            head = (await client.get(url, headers={"Range": "bytes=0-1048575"})).content
            return bool(convert.head_is_protected(head))
    except httpx.HTTPError:
        return False


# A library song added from Apple Music whose catalog entry is gone is usually
# the same recording re-released under a new id: find it by name, and take it
# only when the title matches and the length is the same to the second or two.
TWIN_MIN_SCORE = 0.9
TWIN_MAX_DRIFT_MS = 2000
TWIN_SEARCH_INTERVAL = 1.0
_twin_pace = {"next": 0.0}


def _catalog_link(library: dict) -> list:
    return (((library.get("relationships") or {}).get("catalog")) or {}).get("data") or []


async def _catalog_twin(api: AppleMusicApi, library: dict) -> dict | None:
    # Imported here: importer imports search, which imports this module.
    from .importer import _base_title, score

    a = library.get("attributes") or {}
    length = a.get("durationInMillis")
    if not (a.get("playParams") or {}).get("catalogId") or not a.get("name") or not length:
        return None  # the user's own upload: its library copy is the real one
    results = None
    for wait in (0, 5, 15, 40):
        await asyncio.sleep(max(wait, _twin_pace["next"] - time.monotonic()))
        _twin_pace["next"] = time.monotonic() + TWIN_SEARCH_INTERVAL
        try:
            results = await api.get_search_results(f"{a.get('artistName', '')} {a['name']}", types="songs", limit=10)
            break
        except GamdlApiResponseError as e:
            if e.status_code != 429:
                return None
    best = None
    for song in ((results or {}).get("results", {}).get("songs", {}).get("data") or []):
        c = song.get("attributes") or {}
        drift = abs((c.get("durationInMillis") or 0) - length)
        item = {"name": c.get("name"), "artist": c.get("artistName"), "album": c.get("albumName")}
        if (
            drift <= TWIN_MAX_DRIFT_MS
            and _base_title(c.get("name") or "") == _base_title(a["name"])
            and score(a.get("artistName") or "", a["name"], item) >= TWIN_MIN_SCORE
            and (best is None or drift < best[0])
        ):
            best = (drift, song["id"])
    if best is None:
        return None
    return (await api.get_song(best[1]))["data"][0]


class WebSongInterface(AppleMusicSongInterface):
    """Library songs come from the catalog whenever it has them; the rest only
    when Apple offers them unencrypted (the user's own uploads)."""

    async def get_media(self, media):
        api = self.base.apple_music_api
        if media.is_library:
            relationships = (media.media_metadata or {}).get("relationships") or {}
            if not media.media_metadata or "catalog" not in relationships:
                # Listed without its catalog link because nobody asked for it: ask.
                try:
                    media.media_metadata = (await api.get_library_song(media.media_id))["data"][0]
                except Exception as e:
                    logger.debug("library_catalog_lookup_failed", media_id=media.media_id, error=str(e))
            if media.media_metadata and not _catalog_link(media.media_metadata):
                twin = await _catalog_twin(api, media.media_metadata)
                if twin:
                    a = media.media_metadata.get("attributes") or {}
                    logger.info(f'보관함 곡을 카탈로그에서 다시 찾았습니다: "{a.get("artistName")} - {a.get("name")}"')
                    media.media_id, media.is_library, media.media_metadata = twin["id"], False, twin
        async for item in super().get_media(media):
            yield item

    async def _get_library_stream_info(self, webplayback):
        stream_info = await super()._get_library_stream_info(webplayback)
        if stream_info and await _is_locked_stream(stream_info.audio_track.stream_url):
            raise LockedLibrarySongError(LOCKED_LIBRARY_MESSAGE)
        return stream_info


class WebSongDownloader(AppleMusicSongDownloader):
    async def get_download_item(self, media):
        # get_final_path runs before the first await in here, so this can't
        # leak into another song's name.
        self.base.current_media = media
        try:
            return await super().get_download_item(media)
        finally:
            self.base.current_media = None

    async def stage(self, *args, **kwargs):
        progress.report("decrypt")
        return await super().stage(*args, **kwargs)


class WebMusicVideoDownloader(AppleMusicMusicVideoDownloader):
    async def stage(self, *args, **kwargs):
        progress.report("decrypt")
        return await super().stage(*args, **kwargs)


@dataclass
class Session:
    apple_music_api: AppleMusicApi
    wrapper_api: WrapperApi | None
    downloader: AppleMusicDownloader

    async def close(self) -> None:
        await self.apple_music_api.client.aclose()
        if self.wrapper_api:
            await self.wrapper_api.client.aclose()


async def create_apple_music_api(
    settings: Settings,
) -> tuple[AppleMusicApi, WrapperApi | None]:
    if settings.use_wrapper:
        try:
            wrapper_api = await WebWrapperApi.create(
                base_url=settings.wrapper_url,
                decrypt_host=settings.wrapper_decrypt_host,
                decrypt_port=settings.wrapper_decrypt_port,
            )
        except httpx.HTTPError as e:
            raise SetupError(
                f"wrapper({settings.wrapper_url})에 연결할 수 없습니다: {e}"
            ) from e
        except Exception as e:
            if "not authenticated" in str(e):
                raise SetupError(
                    "wrapper에 로그인되어 있지 않습니다. Wrapper 탭에서 Apple ID로 로그인하세요."
                ) from e
            if "Error fetching wrapper account info" in str(e):
                raise SetupError(
                    f"wrapper({settings.wrapper_url})에 연결할 수 없습니다. 컨테이너가 실행 중인지 확인하세요."
                ) from e
            raise SetupError(f"wrapper 오류: {e}") from e
        try:
            api = await WebAppleMusicApi.create_from_wrapper(
                wrapper_api=wrapper_api,
                language=settings.language,
            )
        except Exception as e:
            await wrapper_api.client.aclose()
            if isinstance(e, GamdlApiResponseError) and "account info" in str(e):
                raise SetupError(
                    f"Apple Music이 wrapper 세션을 거부했습니다 ({e}). Wrapper 탭에서 로그아웃 후 다시 로그인해 보세요."
                ) from e
            raise
        return api, wrapper_api

    cookies_path = Path(settings.cookies_path).expanduser()
    if not cookies_path.is_file():
        raise SetupError(
            "cookies.txt가 없습니다. 설정 탭에서 Apple Music 쿠키 파일을 업로드하거나 wrapper를 사용하세요."
        )
    try:
        api = await WebAppleMusicApi.create_from_netscape_cookies(
            cookies_path=str(cookies_path),
            language=settings.language,
        )
    except ValueError as e:
        raise SetupError(f"쿠키 파일 문제: {e}") from e
    except GamdlApiResponseError as e:
        if "account info" in str(e):
            raise SetupError(
                f"Apple Music이 쿠키/토큰을 거부했습니다 ({e}). "
                "만료되었거나 잘못된 값일 수 있으니 music.apple.com에서 다시 내보내 주세요."
            ) from e
        raise
    return api, None


async def create_session(settings: Settings, prompts: WebPrompts) -> Session:
    if DrmBackend(settings.drm_backend) == DrmBackend.PLAYREADY and not settings.prd_path:
        raise SetupError("PlayReady 백엔드를 쓰려면 .prd 파일 경로가 필요합니다.")

    apple_music_api, wrapper_api = await create_apple_music_api(settings)

    if not apple_music_api.active_subscription:
        await apple_music_api.client.aclose()
        if wrapper_api:
            await wrapper_api.client.aclose()
        raise SetupError("활성화된 Apple Music 구독을 찾지 못했습니다.")

    base_interface = await WebBaseInterface.create(
        apple_music_api=apple_music_api,
        cover_format=CoverFormat(settings.cover_format),
        cover_size=settings.cover_size,
        wvd_path=settings.wvd_path or None,
        wrapper_api=wrapper_api,
        prd_path=settings.prd_path or None,
        drm_backend=DrmBackend(settings.drm_backend),
    )
    song_interface = WebSongInterface(
        base=base_interface,
        synced_lyrics_format=SyncedLyricsFormat(settings.synced_lyrics_format),
        codec_priority=[SongCodec(c) for c in settings.song_codec_priority],
        use_album_date=settings.use_album_date,
        skip_stream_info=settings.synced_lyrics_only,
        ask_codec_function=prompts.ask_song_codec,
    )
    music_video_interface = AppleMusicMusicVideoInterface(
        base=base_interface,
        resolution=MusicVideoResolution(settings.music_video_resolution),
        codec_priority=[MusicVideoCodec(c) for c in settings.music_video_codec_priority],
        ask_video_codec_function=prompts.ask_music_video_video_codec,
        ask_audio_codec_function=prompts.ask_music_video_audio_codec,
    )
    uploaded_video_interface = AppleMusicUploadedVideoInterface(
        base=base_interface,
        quality=UploadedVideoQuality(settings.uploaded_video_quality),
        ask_quality_function=prompts.ask_uploaded_video_quality,
    )
    interface = AppleMusicInterface(
        song=song_interface,
        music_video=music_video_interface,
        uploaded_video=uploaded_video_interface,
        artist_select_media_type_function=prompts.ask_artist_media_type,
        artist_select_items_function=prompts.ask_artist_select_items,
    )

    base_downloader = WebBaseDownloader(
        playlist_track_template=(
            f"{settings.playlist_track_folder_template}/{settings.playlist_track_template}"
            if settings.use_playlist_track_path
            else None
        ),
        single_song_template=settings.single_song_template if settings.single_song_folder else None,
        interface=interface,
        output_path=str(Path(settings.output_path).expanduser()),
        temp_path=str(Path(settings.temp_path).expanduser()),
        nm3u8dlre_path=settings.nm3u8dlre_path,
        ffmpeg_path=settings.ffmpeg_path,
        download_mode=DownloadMode(settings.download_mode),
        album_folder_template=settings.album_folder_template,
        compilation_folder_template=settings.compilation_folder_template,
        no_album_folder_template=settings.no_album_folder_template,
        playlist_folder_template=settings.playlist_folder_template,
        single_disc_file_template=settings.single_disc_file_template,
        multi_disc_file_template=settings.multi_disc_file_template,
        no_album_file_template=settings.no_album_file_template,
        playlist_file_template=settings.playlist_file_template,
        date_tag_template=settings.date_tag_template,
        exclude_tags=settings.exclude_tags or None,
        truncate=settings.truncate,
        silent=True,
    )
    downloader = AppleMusicDownloader(
        song=WebSongDownloader(base=base_downloader),
        music_video=WebMusicVideoDownloader(
            base=base_downloader,
            remux_format=RemuxFormatMusicVideo(settings.music_video_remux_format),
        ),
        uploaded_video=AppleMusicUploadedVideoDownloader(base=base_downloader),
        overwrite=settings.overwrite,
        save_cover=settings.save_cover,
        save_playlist=settings.save_playlist,
        no_synced_lyrics=settings.no_synced_lyrics,
        synced_lyrics_only=settings.synced_lyrics_only,
    )
    return Session(apple_music_api, wrapper_api, downloader)


def artist_auto_select(settings: Settings) -> ArtistMediaType | None:
    return ArtistMediaType(settings.artist_auto_select) if settings.artist_auto_select else None
