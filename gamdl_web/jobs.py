from __future__ import annotations

import asyncio
import os
import re
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

from . import convert, dj, importer, motion
from . import progress
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


SINGLE_SONG_URL_RE = re.compile(r"/song/|[?&]i=\d")

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
    # Live progress while downloading: stage key, 0..1 overall, bytes of the stream.
    stage: str | None = None
    progress: float | None = None
    bytes_done: int | None = None
    bytes_total: int | None = None
    # The downloaded file's real format, e.g. {"codec": "alac", "bits": 24, "rate": 96000}.
    quality: dict[str, Any] | None = None
    isrc: str | None = None
    # Written for DJ software: BPM, key and where they came from (file/getsongbpm/deezer).
    bpm: float | None = None
    music_key: str | None = None
    dj_sources: list[str] | None = None

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
    # Title/artist/artwork to show before the job starts and gamdl reports them.
    preview: dict[str, Any] | None = None
    # Set for a pasted list: its folder name, for the M3U8 and "already downloaded".
    import_name: str | None = None

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
            "preview": self.preview,
            "import_name": self.import_name,
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
        self._dj: dict[str, dict] = {}  # per running job: reference folder index, lookups

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

    def submit(
        self, urls: list[str], overrides: dict[str, Any], preview: dict[str, Any] | None = None,
        import_name: str | None = None,
    ) -> Job:
        job = Job(urls=urls, overrides=overrides, preview=preview, import_name=import_name)
        self.jobs[job.id] = job
        self.queue.put_nowait(job.id)
        self._publish(job)
        return job

    def set_preview(self, job: Job, preview: dict[str, Any]) -> None:
        if job.preview is None and preview:
            job.preview = preview
            self._publish(job)

    def _finish_import(self, job: Job, settings) -> None:
        """Remember what a pasted list got, and write its M3U8 in list order."""
        tracks = [t for t in job.tracks.values() if t.status in {"done", "skipped"} and t.path]
        importer.remember(job.import_name, [t.media_id for t in tracks])
        folder = Path(settings.output_path).expanduser() / "Imports" / job.import_name
        playlist = importer.write_m3u(folder, job.import_name, [t.path for t in tracks])
        if playlist:
            logger.info(f"플레이리스트 저장: {playlist}")

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
            if job.import_name:
                self._finish_import(job, settings)
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
            ctx = self._dj.pop(job.id, None)
            if ctx:
                await ctx["lookup"].close()
            if session:
                await session.close()
            self._publish(job)
            current_job_id.reset(token)

    async def _run_url(self, job: Job, session, settings, url_index: int, url: str) -> None:
        log = logger.bind(action=f"URL {url_index}/{len(job.urls)}")
        log.info(f'처리 중: "{url}"')
        downloader = session.downloader
        # A link to one song (…/song/… or an album link with ?i=) goes to the Songs folder.
        downloader.base.single_song_mode = bool(SINGLE_SONG_URL_RE.search(url))
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
                        track.quality = await convert.audio_quality(existing, settings.ffmpeg_path)
                        self._publish(job)
                        continue

                token = progress.reporter.set(self._progress_reporter(job, track, converting)) if track else None
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
                        if isinstance(e, GamdlDownloaderMediaFileExistsError) and item.final_path and os.path.exists(item.final_path):
                            track.path = item.final_path
                            track.quality = await convert.audio_quality(item.final_path, settings.ffmpeg_path)
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
                            track.quality = await convert.audio_quality(item.final_path, settings.ffmpeg_path)
                            progress.report("finish")
                            await self._tag_extras(item, settings, log)
                            if settings.save_motion_cover:
                                await self._save_motion(item, settings, log, motion_done)
                        if converting and os.path.exists(item.final_path):
                            progress.report("convert")
                            await self._convert(track, item, settings, log)
                        if settings.dj_tags and media_type in {"songs", "library-songs"}:
                            await self._dj_tags(job, track, settings, log)
                        track.status = "done"
                if token is not None:
                    progress.reporter.reset(token)
                if track:
                    track.stage = None
                    track.progress = 1.0 if track.status == "done" else None
                    self._publish(job)
        except GamdlInterfaceUrlParseError as e:
            log.error(f"지원하지 않는 URL입니다: {e}")
            job.error = f"지원하지 않는 URL: {url}"
        except PromptCancelledError:
            log.warning("선택이 취소되어 이 URL을 건너뜁니다")

    def _progress_reporter(self, job: Job, track: Track, converting: bool):
        """Turns stage reports into an overall 0..1 for the track (download is
        most of the time; decrypting, tagging and converting follow)."""
        end = 0.7 if converting else 0.8
        starts = {"download": 0.02, "decrypt": end, "cover": 0.88, "tags": 0.92, "finish": 0.95, "convert": 0.96}
        last = {"t": 0.0, "stage": None}

        def report(stage: str, done: int | None, total: int | None) -> None:
            # gamdl also fetches the cover while preparing the item; only the
            # one after the audio is in counts as a step.
            if stage == "cover" and (track.progress or 0.0) < end:
                return
            value = starts.get(stage, track.progress or 0.0)
            if stage == "download":
                track.bytes_done, track.bytes_total = done, total
                if done is not None and total:
                    value = 0.02 + (end - 0.02) * min(1.0, done / total)
            track.stage = stage
            track.progress = max(track.progress or 0.0, value)
            now = time.monotonic()
            if stage != last["stage"] or now - last["t"] > 0.35:
                last.update(t=now, stage=stage)
                self._publish(job)

        return report

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

    async def _dj_tags(self, job: Job, track: Track, settings, log) -> None:
        """Key/BPM from the user's own files, GetSongBPM or Deezer (never guessed)."""
        if not track.path or Path(track.path).suffix.lower() not in dj.AUDIO_EXTENSIONS:
            return
        ctx = self._dj.get(job.id)
        if ctx is None:
            ref = None
            if settings.dj_reference_dir:
                ref = await asyncio.to_thread(dj.ReferenceFolder, settings.dj_reference_dir)
                log.info(f"기존 파일 {len(ref.entries)}곡에서 키·BPM을 찾습니다")
            ctx = self._dj[job.id] = {"ref": ref, "lookup": dj.Lookup(settings.getsongbpm_api_key)}
        try:
            result = await dj.tag_track(
                track.path, song_id=track.media_id, title=track.title, artist=track.artist, isrc=track.isrc,
                reference=ctx["ref"], lookup=ctx["lookup"], notation=settings.dj_key_notation,
            )
        except Exception as e:
            log.warning(f'키·BPM을 넣지 못했습니다 "{track.title}": {e}')
            return
        track.bpm, track.music_key, track.dj_sources = result["bpm"], result["key"], result["sources"]

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
                isrc=attributes.get("isrc"),
            )
            job.tracks[key] = track
        else:
            track.title = attributes.get("name") or track.title
            track.artist = attributes.get("artistName") or track.artist
            track.kind = media_type or track.kind
            track.artwork = track.artwork or _artwork(attributes, 300)
            track.isrc = track.isrc or attributes.get("isrc")
        return track
