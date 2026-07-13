from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from yt_clipper.application.ports import (
    DownloadJobRepository,
    FileStorage,
    JobQueue,
    MediaProcessor,
    VideoProvider,
)
from yt_clipper.domain.exceptions import DomainError, InvalidClipRangeError
from yt_clipper.domain.video import ClipRange, DownloadJob


@dataclass(slots=True)
class CreateDownloadCommand:
    source_url: str
    start_seconds: float | None = None
    end_seconds: float | None = None


class CreateDownloadUseCase:
    def __init__(self, repository: DownloadJobRepository, queue: JobQueue) -> None:
        self.repository = repository
        self.queue = queue

    def execute(self, command: CreateDownloadCommand) -> DownloadJob:
        clip_range = self._build_clip_range(command)
        job = DownloadJob(source_url=command.source_url, clip_range=clip_range)
        self.repository.add(job)
        self.queue.enqueue_download(job.id)
        return job

    @staticmethod
    def _build_clip_range(command: CreateDownloadCommand) -> ClipRange | None:
        if command.start_seconds is None and command.end_seconds is None:
            return None
        if command.start_seconds is None or command.end_seconds is None:
            raise InvalidClipRangeError("start_seconds and end_seconds must be provided together")
        return ClipRange(command.start_seconds, command.end_seconds)


class GetDownloadUseCase:
    def __init__(self, repository: DownloadJobRepository) -> None:
        self.repository = repository

    def execute(self, job_id: UUID) -> DownloadJob | None:
        return self.repository.get(job_id)


class ExecuteDownloadJobUseCase:
    def __init__(
        self,
        repository: DownloadJobRepository,
        video_provider: VideoProvider,
        media_processor: MediaProcessor,
        storage: FileStorage,
    ) -> None:
        self.repository = repository
        self.video_provider = video_provider
        self.media_processor = media_processor
        self.storage = storage

    def execute(self, job_id: UUID) -> DownloadJob:
        job = self.repository.get(job_id)
        if job is None:
            raise DomainError(f"download job not found: {job_id}")

        job.mark_running()
        self.repository.update(job)

        try:
            downloaded_path = self.video_provider.download_best(
                job.source_url,
                self.storage.prepare_download_path(job),
            )
            output_path = self._clip_if_needed(job, downloaded_path)
            job.mark_completed(str(output_path))
        except Exception as exc:
            job.mark_failed(str(exc))
            with suppress(Exception):
                self.storage.cleanup_download_path(job)
            self.repository.update(job)
            raise

        self.repository.update(job)
        return job

    def _clip_if_needed(self, job: DownloadJob, downloaded_path: Path) -> Path:
        if job.clip_range is None:
            return downloaded_path
        return self.media_processor.clip(
            downloaded_path,
            job.clip_range,
            self.storage.prepare_clip_path(job, downloaded_path),
        )
