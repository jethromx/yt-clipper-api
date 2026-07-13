from __future__ import annotations

from pathlib import Path
from typing import Protocol
from uuid import UUID

from yt_clipper.domain.video import ClipRange, DownloadJob, VideoMetadata


class DownloadJobRepository(Protocol):
    def add(self, job: DownloadJob) -> DownloadJob: ...

    def get(self, job_id: UUID) -> DownloadJob | None: ...

    def update(self, job: DownloadJob) -> DownloadJob: ...


class JobQueue(Protocol):
    def enqueue_download(self, job_id: UUID) -> None: ...


class VideoProvider(Protocol):
    def get_metadata(self, source_url: str) -> VideoMetadata: ...

    def download_best(self, source_url: str, output_dir: Path) -> Path: ...


class MediaProcessor(Protocol):
    def clip(self, input_path: Path, clip_range: ClipRange, output_path: Path) -> Path: ...


class FileStorage(Protocol):
    def prepare_download_path(self, job: DownloadJob) -> Path: ...

    def prepare_clip_path(self, job: DownloadJob, source_path: Path) -> Path: ...

    def cleanup_download_path(self, job: DownloadJob) -> None: ...

    def resolve(self, relative_path: str) -> Path: ...
