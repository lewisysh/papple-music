from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

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

from .config import Settings
from .prompts import WebPrompts

logger = structlog.get_logger("gamdl_web")


class SetupError(Exception):
    """A problem the user has to fix in settings before anything downloads."""


# The artwork server never upscales: asking for more than the original returns
# the original resolution.
MAX_COVER_SIZE = 10000


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
        if not cover_url:
            return None
        try:
            return await super().get_cover_bytes(cover_url)
        except httpx.HTTPError as e:
            logger.warning(f"커버 이미지를 받지 못해 커버 없이 진행합니다: {e}")
            return None

    async def get_cover(self, metadata: dict):
        cover = await super().get_cover(metadata)
        if cover.file_extension is None:
            # gamdl builds "Cover" + extension later, so keep it a string.
            cover.url = None
            cover.file_extension = ".jpg"
        return cover


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

    def __init__(self, *args, playlist_track_template: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.playlist_track_template = playlist_track_template

    def get_final_path(self, tags, file_extension, playlist_tags):
        if not (self.playlist_track_template and playlist_tags and playlist_tags.title):
            return super().get_final_path(tags, file_extension, playlist_tags)

        # Reuse gamdl's formatting by pointing every template at the playlist one
        # for this call; nothing awaits in between, so no other item sees it.
        folder, _, file = self.playlist_track_template.rpartition("/")
        saved = {attr: getattr(self, attr) for attr in self._TEMPLATE_ATTRS}
        for attr in self._TEMPLATE_ATTRS:
            setattr(self, attr, folder if attr.endswith("folder_template") else file)
        try:
            return super().get_final_path(tags, file_extension, playlist_tags)
        finally:
            for attr, value in saved.items():
                setattr(self, attr, value)

    async def apply_tags(self, media_path, tags, cover_bytes):
        if "cover" in (self.exclude_tags or []):
            cover_bytes = None
        await super().apply_tags(media_path, tags, cover_bytes)


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
            wrapper_api = await WrapperApi.create(
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
            api = await AppleMusicApi.create_from_wrapper(
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
        api = await AppleMusicApi.create_from_netscape_cookies(
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
    song_interface = AppleMusicSongInterface(
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
            settings.playlist_track_template if settings.use_playlist_track_path else None
        ),
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
        song=AppleMusicSongDownloader(base=base_downloader),
        music_video=AppleMusicMusicVideoDownloader(
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
