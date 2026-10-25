from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
from typing import Any

from gamdl.api.wrapper import WrapperApi
from gamdl.downloader import AppleMusicBaseDownloader
from gamdl.downloader.enums import DownloadMode, RemuxFormatMusicVideo
from gamdl.interface import (
    ArtistMediaType,
    CoverFormat,
    DrmBackend,
    MusicVideoCodec,
    MusicVideoResolution,
    SongCodec,
    SyncedLyricsFormat,
    UploadedVideoQuality,
)
from pydantic import BaseModel, Field, field_validator

DATA_DIR = Path(
    os.environ.get("GAMDL_WEB_DATA_DIR", Path.home() / ".gamdl-web")
).expanduser()
SETTINGS_PATH = DATA_DIR / "settings.json"

_downloader_defaults = {
    name: param.default
    for name, param in inspect.signature(
        AppleMusicBaseDownloader.__init__
    ).parameters.items()
}
_wrapper_defaults = {
    name: param.default
    for name, param in inspect.signature(WrapperApi.create).parameters.items()
}


def _env(name: str, default: Any) -> Any:
    return os.environ.get(f"GAMDL_WEB_{name}", default)


# Fields validated against gamdl's own enums so a bad value is rejected on save
# instead of failing halfway through a download.
ENUM_FIELDS: dict[str, type] = {
    "synced_lyrics_format": SyncedLyricsFormat,
    "music_video_resolution": MusicVideoResolution,
    "music_video_remux_format": RemuxFormatMusicVideo,
    "uploaded_video_quality": UploadedVideoQuality,
    "cover_format": CoverFormat,
    "download_mode": DownloadMode,
    "drm_backend": DrmBackend,
}
ENUM_LIST_FIELDS: dict[str, type] = {
    "song_codec_priority": SongCodec,
    "music_video_codec_priority": MusicVideoCodec,
}
LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]
OUTPUT_FORMATS = ["original", "flac", "wav", "mp3"]
MP3_BITRATES = ["320k", "256k", "192k", "V0"]


class Settings(BaseModel):
    # General
    output_path: str = Field(
        default_factory=lambda: _env("OUTPUT_PATH", str(Path.home() / "Music" / "gamdl"))
    )
    temp_path: str = Field(default_factory=lambda: _env("TEMP_PATH", str(DATA_DIR / "tmp")))
    cookies_path: str = Field(
        default_factory=lambda: _env("COOKIES_PATH", str(DATA_DIR / "cookies.txt"))
    )
    language: str = "en-US"
    log_level: str = "INFO"
    artist_auto_select: str = ""

    # Wrapper
    use_wrapper: bool = Field(
        default_factory=lambda: _env("USE_WRAPPER", "0").lower() in {"1", "true", "yes"}
    )
    wrapper_url: str = Field(default_factory=lambda: _env("WRAPPER_URL", "http://127.0.0.1:8080"))
    wrapper_decrypt_host: str = Field(
        default_factory=lambda: _env(
            "WRAPPER_DECRYPT_HOST", _wrapper_defaults["decrypt_host"]
        )
    )
    wrapper_decrypt_port: int = Field(
        default_factory=lambda: int(
            _env("WRAPPER_DECRYPT_PORT", _wrapper_defaults["decrypt_port"])
        )
    )
    wrapper_container: str = Field(
        default_factory=lambda: _env("WRAPPER_CONTAINER", "wrapper-v2")
    )

    # Songs
    song_codec_priority: list[str] = ["aac-web"]
    # Exact HLS audio group picked in the download sheet, e.g. audio-alac-stereo-96000-24.
    song_variant: str = ""
    synced_lyrics_format: str = "lrc"
    no_synced_lyrics: bool = False
    synced_lyrics_only: bool = False
    use_album_date: bool = False

    # Music videos / post videos
    music_video_resolution: str = "1080p"
    music_video_codec_priority: list[str] = ["h264", "h265"]
    music_video_remux_format: str = "m4v"
    uploaded_video_quality: str = "best"

    # Cover & files
    cover_format: str = "jpg"
    cover_size: int = 1200
    save_cover: bool = False
    save_playlist: bool = False
    overwrite: bool = False

    # Conversion after download
    output_format: str = "original"
    mp3_bitrate: str = "320k"
    keep_original: bool = False
    save_motion_cover: bool = False

    # Download tools
    download_mode: str = _downloader_defaults["download_mode"].value
    ffmpeg_path: str = _downloader_defaults["ffmpeg_path"]
    nm3u8dlre_path: str = _downloader_defaults["nm3u8dlre_path"]

    # DRM
    drm_backend: str = "widevine"
    wvd_path: str = ""
    prd_path: str = ""

    # Templates
    album_folder_template: str = _downloader_defaults["album_folder_template"]
    compilation_folder_template: str = _downloader_defaults["compilation_folder_template"]
    no_album_folder_template: str = _downloader_defaults["no_album_folder_template"]
    playlist_folder_template: str = _downloader_defaults["playlist_folder_template"]
    single_disc_file_template: str = _downloader_defaults["single_disc_file_template"]
    multi_disc_file_template: str = _downloader_defaults["multi_disc_file_template"]
    no_album_file_template: str = _downloader_defaults["no_album_file_template"]
    playlist_file_template: str = _downloader_defaults["playlist_file_template"]
    date_tag_template: str = _downloader_defaults["date_tag_template"]
    # Songs downloaded from a playlist URL go under this path instead of the
    # album templates (gamdl itself always files them by album).
    use_playlist_track_path: bool = False
    playlist_track_template: str = "Playlists/{playlist_title}/{playlist_track:02d} {title}"
    exclude_tags: list[str] = []
    truncate: int | None = None

    @field_validator(*ENUM_FIELDS)
    @classmethod
    def _check_enum(cls, value: str, info) -> str:
        ENUM_FIELDS[info.field_name](value)
        return value

    @field_validator(*ENUM_LIST_FIELDS)
    @classmethod
    def _check_enum_list(cls, value: list[str], info) -> list[str]:
        if not value:
            raise ValueError("at least one codec is required")
        for item in value:
            ENUM_LIST_FIELDS[info.field_name](item)
        return value

    @field_validator("artist_auto_select")
    @classmethod
    def _check_artist_auto_select(cls, value: str) -> str:
        if value:
            ArtistMediaType(value)
        return value

    @field_validator("output_format")
    @classmethod
    def _check_output_format(cls, value: str) -> str:
        if value not in OUTPUT_FORMATS:
            raise ValueError(f"must be one of {', '.join(OUTPUT_FORMATS)}")
        return value

    @field_validator("mp3_bitrate")
    @classmethod
    def _check_mp3_bitrate(cls, value: str) -> str:
        if value not in MP3_BITRATES:
            raise ValueError(f"must be one of {', '.join(MP3_BITRATES)}")
        return value

    @field_validator("log_level")
    @classmethod
    def _check_log_level(cls, value: str) -> str:
        value = value.upper()
        if value not in LOG_LEVELS:
            raise ValueError(f"must be one of {', '.join(LOG_LEVELS)}")
        return value

    @field_validator("wrapper_url")
    @classmethod
    def _check_wrapper_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("must start with http:// or https://")
        return value.rstrip("/")

    def merged(self, overrides: dict[str, Any]) -> Settings:
        return Settings.model_validate({**self.model_dump(), **overrides})


# Settings a single download job may override from the download form.
JOB_OVERRIDE_FIELDS = {
    "song_codec_priority",
    "song_variant",
    "music_video_codec_priority",
    "format_label",
    "use_wrapper",
    "music_video_resolution",
    "synced_lyrics_only",
    "overwrite",
    "save_cover",
}


class SettingsStore:
    def __init__(self, path: Path = SETTINGS_PATH):
        self.path = path
        self._settings = self._load()

    def _load(self) -> Settings:
        if not self.path.exists():
            return Settings()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return Settings()
        known = {k: v for k, v in data.items() if k in Settings.model_fields}
        try:
            return Settings.model_validate(known)
        except ValueError:
            return Settings()

    def get(self) -> Settings:
        return self._settings

    def update(self, changes: dict[str, Any]) -> Settings:
        changes = {k: v for k, v in changes.items() if k in Settings.model_fields}
        self._settings = self._settings.merged(changes)
        self.save()
        return self._settings

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(self._settings.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp_path.replace(self.path)
