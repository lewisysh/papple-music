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

from . import convert, dj, importer, motion, wrapper
from . import progress
from .config import Settings, SettingsStore
from .events import EventBus
from .logs import current_job_id
from .prompts import PromptBroker, PromptCancelledError, WebPrompts, _artwork
from .runner import LockedLibrarySongError, SetupError, artist_auto_select, create_session

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
    LockedLibrarySongError,
)
# Last line of defence; LockedLibrarySongError normally stops these before download.
PROTECTED_MESSAGE = "받은 파일이 잠겨(DRM) 있어서 저장하지 않았습니다."
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
VIDEO_TYPES = {"music-videos", "library-music-videos", "uploaded-videos"}


async def _file_quality(path: str, media_type: str | None, settings: Settings) -> dict | None:
    """The real format of a downloaded file: resolution for videos, audio otherwise."""
    if media_type in VIDEO_TYPES:
        return await asyncio.to_thread(convert.video_quality, path)
    return await convert.audio_quality(path, settings.ffmpeg_path)


COLLECTION_TYPES = {
    "albums",
    "library-albums",
    "playlists",
    "library-playlists",
    "artists",
}
FINISHED = {"done", "error", "cancelled"}
PLAYLIST_COVER_MAX = 3000
PLAYLIST_FOLDER_RE = re.compile(r"%playlist(?:_id)?%|\{playlist_(?:title|id)\}", re.IGNORECASE)


SINGLE_SONG_URL_RE = re.compile(r"/song/|[?&]i=\d|/library/songs/")

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
    # Each link's place in the pasted list (1-based), for %position%.
    positions: list[int] | None = None

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
        self._files: dict[str, list[str]] = {}
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
        import_name: str | None = None, positions: list[int] | None = None,
    ) -> Job:
        if positions is not None and len(positions) != len(urls):
            positions = None
        job = Job(urls=urls, overrides=overrides, preview=preview, import_name=import_name, positions=positions)
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
        importer.remember(job.import_name, {t.media_id: t.path for t in tracks})
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

    def saved(self, urls: list[str]) -> dict[str, bool]:
        """Whether each link's download is going or still on disk, so the page can
        offer it again once its files are gone."""
        active = {u for job in self.jobs.values() if job.status not in FINISHED for u in job.urls}
        return {
            u: u in active or (bool(self._files.get(u)) and all(os.path.exists(p) for p in self._files[u]))
            for u in urls
        }

    def _remember_files(self, job: Job) -> None:
        """What each link saved. Empty when any of its songs didn't make it."""
        for index, url in enumerate(job.urls, 1):
            tracks = [t for t in job.tracks.values() if t.key.startswith(f"{index}:")]
            complete = all(t.status in {"done", "skipped"} and t.path for t in tracks)
            self._files[url] = [t.path for t in tracks] if complete else []

    def retry(self, job_id: str) -> Job:
        job = self.jobs[job_id]
        return self.submit(job.urls, job.overrides, job.preview, job.import_name, job.positions)

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
            self._remember_files(job)
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
        if job.positions:
            downloader.base.list_position = job.positions[url_index - 1]
            downloader.base.list_total = max(job.positions)
        else:
            downloader.base.list_position, downloader.base.list_total = url_index, len(job.urls)
        motion_done: set[str] = set()
        cover_done: set[str] = set()
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

                if not media.partial and not media.error:
                    try:
                        await self._save_playlist_cover(item, downloader, settings, log, cover_done)
                    except Exception as e:
                        log.warning(f"플레이리스트 커버를 저장하지 못했습니다: {e}")

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

                if (
                    track is not None
                    and media_type in {"songs", "library-songs"}
                    and item.final_path
                    and os.path.exists(item.final_path)
                    and await asyncio.to_thread(convert.is_protected, item.final_path)
                ):
                    # A locked file from before is in the way: fetch the song again.
                    os.remove(item.final_path)
                    log.info(f'잠긴 파일을 지우고 다시 받습니다: "{track.title}"')

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
                            track.quality = await _file_quality(item.final_path, media_type, settings)
                except Exception as e:
                    message = await wrapper.explain_error(settings, str(e) or type(e).__name__)
                    log.error(
                        f'오류 "{track.title if track else media.media_id}": {message}',
                        exception=traceback.format_exc(),
                    )
                    if track:
                        track.status = "error"
                        track.message = message
                    else:
                        job.error = message
                else:
                    # Tagging, converting and the like: a failure here is this song's,
                    # not the whole job's.
                    try:
                        protected = (
                            track is not None
                            and not media.partial
                            and media_type in {"songs", "library-songs"}
                            and os.path.exists(item.final_path)
                            and await asyncio.to_thread(convert.is_protected, item.final_path)
                        )
                        if protected:
                            for leftover in (item.final_path, item.synced_lyrics_path):
                                if leftover and os.path.exists(leftover):
                                    os.remove(leftover)
                            log.error(f'오류 "{track.title}": {PROTECTED_MESSAGE}')
                            track.status = "error"
                            track.message = PROTECTED_MESSAGE
                        elif track and not media.partial:
                            track.path = item.final_path
                            if media_type in VIDEO_TYPES and os.path.exists(item.final_path):
                                track.quality = await _file_quality(item.final_path, media_type, settings)
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
                            note = getattr(media.stream_info, "resolution_note", None)
                            if note:
                                track.message = note
                    except Exception as e:
                        message = str(e) or type(e).__name__
                        log.error(f'오류 "{track.title if track else media.media_id}": {message}', exception=traceback.format_exc())
                        if track:
                            track.status = "error"
                            track.message = message
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

    async def _save_playlist_cover(self, item, downloader, settings, log, done: set[str]) -> None:
        """Save the playlist's own artwork once, in the playlist's folder, as
        Cover.jpg. Runs before the first song so an album cover doesn't take the name."""
        media = item.media
        if not (media.playlist_tags and settings.use_playlist_track_path and item.final_path):
            return
        # Only a folder of this playlist's own: one every playlist shares (like
        # "Songs") would get each playlist's cover in turn.
        if not PLAYLIST_FOLDER_RE.search(settings.playlist_track_folder_template):
            return
        # The track template can add folders below it (artist/album): go back up,
        # so album folders keep their own cover.
        folder = os.path.dirname(item.final_path)
        for _ in range(settings.playlist_track_template.count("/")):
            folder = os.path.dirname(folder)
        if folder in done:
            return
        done.add(folder)
        target = os.path.join(folder, "Cover.jpg")
        if os.path.exists(target) and not settings.overwrite:
            return
        artwork = ((media.playlist_metadata or {}).get("attributes") or {}).get("artwork") or {}
        # Only the blanks: what follows them can be the crop that makes a wide
        # editorial image into the square cover. Apple ignores that crop at very
        # large sizes and sends the wide original, so the size is capped.
        size = str(min(settings.cover_size, PLAYLIST_COVER_MAX))
        url = (artwork.get("url") or "").replace("{w}", size).replace("{h}", size).replace("{c}", "bb").replace("{f}", "jpg")
        if not url:
            return
        data = await downloader.base.interface.base.get_cover_bytes(url)
        if data:
            os.makedirs(folder, exist_ok=True)
            Path(target).write_bytes(data)
            log.info("플레이리스트 커버 저장: Cover.jpg")

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
