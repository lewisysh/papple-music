from __future__ import annotations

import asyncio
import os
import time
import traceback
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog
from gamdl.downloader import (
    GamdlDownloaderDependencyNotFoundError,
    GamdlDownloaderMediaFileExistsError,
    GamdlDownloaderSyncedLyricsOnlyError,
)
from gamdl.interface import (
    GamdlInterfaceArtistMediaTypeError,
    GamdlInterfaceDecryptionNotAvailableError,
    GamdlInterfaceFlatFilterExcludedError,
    GamdlInterfaceFormatNotAvailableError,
    GamdlInterfaceMediaNotStreamableError,
    GamdlInterfaceUrlParseError,
)

from . import convert, motion
from .config import SettingsStore
from .events import EventBus
from .logs import current_job_id
from .prompts import PromptBroker, PromptCancelledError, WebPrompts, _artwork
from .runner import SetupError, artist_auto_select, create_session

logger = structlog.get_logger("gamdl_web")

SKIP_ERRORS = (
    GamdlInterfaceMediaNotStreamableError,
    GamdlInterfaceFormatNotAvailableError,
    GamdlInterfaceDecryptionNotAvailableError,
    GamdlInterfaceArtistMediaTypeError,
    GamdlDownloaderMediaFileExistsError,
    GamdlDownloaderDependencyNotFoundError,
    GamdlInterfaceFlatFilterExcludedError,
    PromptCancelledError,
)
SKIP_MESSAGES = {
    GamdlInterfaceMediaNotStreamableError: "스트리밍할 수 없는 항목",
    GamdlInterfaceFormatNotAvailableError: "고른 코덱으로 제공되지 않음",
    GamdlInterfaceDecryptionNotAvailableError: "복호화할 수 없음",
    GamdlInterfaceArtistMediaTypeError: "해당 종류의 항목이 없음",
    GamdlDownloaderMediaFileExistsError: "이미 받은 파일",
    GamdlInterfaceFlatFilterExcludedError: "필터로 제외됨",
    PromptCancelledError: "선택을 건너뜀",
}
TRACK_TYPES = {
    None,
    "songs",
    "library-songs",
    "music-videos",
    "library-music-videos",
    "uploaded-videos",
}
COLLECTION_TYPES = {
    "albums",
    "library-albums",
    "playlists",
    "library-playlists",
    "artists",
}
FINISHED = {"done", "error", "cancelled"}


@dataclass
class Track:
    key: str
    media_id: str
    index: int
    total: int | None
    title: str
    artist: str | None = None
    kind: str | None = None
    artwork: str | None = None
    status: str = "preparing"
    message: str | None = None
    path: str | None = None

    def public(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class Job:
    urls: list[str]
    overrides: dict[str, Any]
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    url_index: int = 0
    collections: list[dict[str, Any]] = field(default_factory=list)
    tracks: dict[str, Track] = field(default_factory=dict)
    logs: deque = field(default_factory=lambda: deque(maxlen=1000))
    error: str | None = None

    def counts(self) -> dict[str, int]:
        counts = {"total": len(self.tracks)}
        for track in self.tracks.values():
            counts[track.status] = counts.get(track.status, 0) + 1
        return counts

    def public(self, log_tail: int = 0) -> dict[str, Any]:
        data = {
            "id": self.id,
            "urls": self.urls,
            "overrides": self.overrides,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "url_index": self.url_index,
            "collections": self.collections,
            "tracks": [t.public() for t in self.tracks.values()],
            "counts": self.counts(),
            "error": self.error,
        }
        if log_tail:
            data["logs"] = list(self.logs)[-log_tail:]
        return data


def _media_info(media) -> tuple[str | None, dict]:
    metadata = media.media_metadata or {}
    return metadata.get("type"), metadata.get("attributes") or {}


class JobManager:
    def __init__(self, store: SettingsStore, bus: EventBus, broker: PromptBroker):
        self.store = store
        self.bus = bus
        self.broker = broker
        self.jobs: dict[str, Job] = {}
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self._running: tuple[str, asyncio.Task] | None = None
        self.motion = None  # MotionService, attached by the app

    # ---- lifecycle -------------------------------------------------------

    def start(self) -> None:
        self._worker = asyncio.create_task(self._work())

    async def stop(self) -> None:
        if self._running:
            self._running[1].cancel()
        if self._worker:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass

    # ---- public API ------------------------------------------------------

    def submit(self, urls: list[str], overrides: dict[str, Any]) -> Job:
        job = Job(urls=urls, overrides=overrides)
        self.jobs[job.id] = job
        self.queue.put_nowait(job.id)
        self._publish(job)
        return job

    def cancel(self, job_id: str) -> None:
        job = self.jobs[job_id]
        if job.status == "queued":
            job.status = "cancelled"
            job.finished_at = time.time()
            self._publish(job)
        elif self._running and self._running[0] == job_id:
            self._running[1].cancel()

    def remove(self, job_id: str) -> None:
        job = self.jobs[job_id]
        if job.status not in FINISHED:
            raise ValueError("진행 중인 작업은 삭제할 수 없습니다")
        del self.jobs[job_id]
        self.bus.publish("job_removed", {"id": job_id})

    def clear_finished(self) -> None:
        for job_id in [j.id for j in self.jobs.values() if j.status in FINISHED]:
            self.remove(job_id)

    def retry(self, job_id: str) -> Job:
        job = self.jobs[job_id]
        return self.submit(job.urls, job.overrides)

    def append_log(self, job_id: str, entry: dict[str, Any]) -> None:
        job = self.jobs.get(job_id)
        if job is None:
            return
        job.logs.append(entry)
        self.bus.publish("log", {"job_id": job_id, "entry": entry})

    def snapshot(self) -> list[dict[str, Any]]:
        return [job.public(log_tail=200) for job in self.jobs.values()]

    # ---- internals -------------------------------------------------------

    def _publish(self, job: Job) -> None:
        self.bus.publish("job", job.public())

    async def _work(self) -> None:
        while True:
            job_id = await self.queue.get()
            job = self.jobs.get(job_id)
            if job is None or job.status != "queued":
                continue
            task = asyncio.create_task(self._run(job))
            self._running = (job_id, task)
            try:
                await task
            except asyncio.CancelledError:
                if not task.cancelled():
                    raise
            finally:
                self._running = None

    async def _run(self, job: Job) -> None:
        token = current_job_id.set(job.id)
        job.status = "running"
        job.started_at = time.time()
        self._publish(job)
        session = None
        try:
            settings = self.store.get().merged(job.overrides)
            prompts = WebPrompts(
                self.broker, job.id, artist_auto_select(settings), settings.song_variant
            )
            logger.info("세션 준비 중" + (" (wrapper 사용)" if settings.use_wrapper else ""))
            session = await create_session(settings, prompts)
            if session.apple_music_api.account_restrictions:
                logger.warning("계정에 콘텐츠 제한이 걸려 있어 일부 항목은 받을 수 없을 수 있습니다")
            for url_index, url in enumerate(job.urls, 1):
                job.url_index = url_index
                self._publish(job)
                await self._run_url(job, session, settings, url_index, url)
            job.status = "done"
            counts = job.counts()
            logger.info(
                f"완료 — 성공 {counts.get('done', 0)}, 건너뜀 {counts.get('skipped', 0)}, 오류 {counts.get('error', 0)}"
            )
        except asyncio.CancelledError:
            job.status = "cancelled"
            for track in job.tracks.values():
                if track.status in {"preparing", "downloading"}:
                    track.status = "cancelled"
            logger.warning("작업이 취소되었습니다")
            raise
        except SetupError as e:
            job.status = "error"
            job.error = str(e)
            logger.error(str(e))
        except Exception as e:
            job.status = "error"
            job.error = f"{type(e).__name__}: {e}"
            logger.error(job.error, exception=traceback.format_exc())
        finally:
            job.finished_at = time.time()
            self.broker.cancel_job(job.id)
            if session:
                await session.close()
            self._publish(job)
            current_job_id.reset(token)

    async def _run_url(self, job: Job, session, settings, url_index: int, url: str) -> None:
        log = logger.bind(action=f"URL {url_index}/{len(job.urls)}")
        log.info(f'처리 중: "{url}"')
        downloader = session.downloader
        motion_done: set[str] = set()
        try:
            async for item in downloader.get_download_item_from_url(url):
                media = item.media
                media_type, attributes = _media_info(media)

                if media.partial and media_type in COLLECTION_TYPES and not media.error:
                    job.collections.append(
                        {
                            "type": media_type,
                            "title": attributes.get("name"),
                            "artist": attributes.get("artistName")
                            or attributes.get("curatorName"),
                            "count": attributes.get("trackCount"),
                            "artwork": _artwork(attributes, 300),
                            "url": url,
                        }
                    )
                    self._publish(job)

                track = None
                if media_type in TRACK_TYPES and (media.media_id or media.media_metadata):
                    track = self._upsert_track(job, url_index, media, media_type, attributes)
                    if not media.partial:
                        track.status = "downloading"
                    self._publish(job)

                converting = (
                    track is not None
                    and settings.output_format != "original"
                    and media_type in {"songs", "library-songs"}
                    and not media.partial
                    and not media.error
                    and item.final_path
                )
                if converting and not settings.overwrite:
                    existing = convert.target_path(item.final_path, settings.output_format)
                    if os.path.exists(existing):
                        track.status = "skipped"
                        track.message = SKIP_MESSAGES[GamdlDownloaderMediaFileExistsError]
                        track.path = existing
                        self._publish(job)
                        continue

                try:
                    await downloader.download(item)
                except GamdlDownloaderSyncedLyricsOnlyError:
                    if track:
                        track.status = "done"
                        track.message = "가사만 저장"
                        track.path = item.synced_lyrics_path
                except SKIP_ERRORS as e:
                    log.warning(f'건너뜀 "{track.title if track else media.media_id}": {e}')
                    if track:
                        track.status = "skipped"
                        track.message = SKIP_MESSAGES.get(type(e), str(e))
                except Exception as e:
                    log.error(
                        f'오류 "{track.title if track else media.media_id}": {e}',
                        exception=traceback.format_exc(),
                    )
                    if track:
                        track.status = "error"
                        track.message = str(e) or type(e).__name__
                    else:
                        job.error = str(e)
                else:
                    if track and not media.partial:
                        track.path = item.final_path
                        if media_type in {"songs", "library-songs"} and os.path.exists(item.final_path):
                            await self._tag_extras(item, settings, log)
                            if settings.save_motion_cover:
                                await self._save_motion(item, settings, log, motion_done)
                        if converting and os.path.exists(item.final_path):
                            track.message = "변환 중…"
                            self._publish(job)
                            await self._convert(track, item, settings, log)
                        track.status = "done"
                if track:
                    self._publish(job)
        except GamdlInterfaceUrlParseError as e:
            log.error(f"지원하지 않는 URL입니다: {e}")
            job.error = f"지원하지 않는 URL: {url}"
        except PromptCancelledError:
            log.warning("선택이 취소되어 이 URL을 건너뜁니다")

    async def _tag_extras(self, item, settings, log) -> None:
        try:
            await asyncio.to_thread(
                convert.write_mp4_extras,
                item.final_path,
                convert.extra_tags(item.media.media_metadata),
                settings.exclude_tags,
            )
        except Exception as e:
            log.warning(f"추가 태그(레이블·UPC 등)를 쓰지 못했습니다: {e}")

    async def _save_motion(self, item, settings, log, done: set[str]) -> None:
        """Save the album's motion cover once per album folder as Cover.mp4."""
        if self.motion is None or (item.media.playlist_tags and settings.use_playlist_track_path):
            return
        albums = ((item.media.media_metadata or {}).get("relationships") or {}).get("albums", {}).get("data") or []
        folder = os.path.dirname(item.final_path)
        if not albums or folder in done:
            return
        done.add(folder)
        target = os.path.join(folder, "Cover.mp4")
        if os.path.exists(target) and not settings.overwrite:
            return
        try:
            master = await self.motion.master(albums[0]["id"])
            if master:
                await motion.save(master, Path(target), "best", settings.ffmpeg_path)
                log.info("움직이는 커버 저장: Cover.mp4")
        except Exception as e:
            log.warning(f"움직이는 커버를 저장하지 못했습니다: {e}")

    async def _convert(self, track: Track, item, settings, log) -> None:
        try:
            new_path, note = await convert.convert(
                item.final_path,
                settings.output_format,
                ffmpeg=settings.ffmpeg_path,
                mp3_bitrate=settings.mp3_bitrate,
                keep_original=settings.keep_original,
            )
        except Exception as e:
            log.error(f'변환 실패 "{track.title}": {e}', exception=traceback.format_exc())
            track.message = f"변환 실패, m4a로 남김: {e}"
            return
        track.message = note
        if new_path:
            track.path = new_path
            log.info(f'{note}: "{track.title}"')
            if item.playlist_file_path and settings.save_playlist:
                convert.retarget_playlist(item.playlist_file_path, item.final_path, new_path)

    def _upsert_track(self, job: Job, url_index: int, media, media_type, attributes) -> Track:
        key = f"{url_index}:{media.media_id}"
        track = job.tracks.get(key)
        if track is None:
            track = Track(
                key=key,
                media_id=media.media_id,
                index=(media.index or 0) + 1,
                total=media.total or None,
                title=attributes.get("name") or media.media_id,
                artist=attributes.get("artistName"),
                kind=media_type,
                artwork=_artwork(attributes, 300),
            )
            job.tracks[key] = track
        else:
            track.title = attributes.get("name") or track.title
            track.artist = attributes.get("artistName") or track.artist
            track.kind = media_type or track.kind
            track.artwork = track.artwork or _artwork(attributes, 300)
        return track
