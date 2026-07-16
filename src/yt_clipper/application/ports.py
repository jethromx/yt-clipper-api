from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from yt_clipper.domain.trends import TrendingVideo
from yt_clipper.domain.video import (
    ClipRange,
    DownloadJob,
    TikTokCaption,
    VideoMetadata,
    VideoSearchResult,
)


@dataclass(frozen=True, slots=True)
class DownloadResult:
    path: Path
    metadata: VideoMetadata


class DownloadJobRepository(Protocol):
    def add(self, job: DownloadJob) -> DownloadJob: ...

    def get(self, job_id: UUID) -> DownloadJob | None: ...

    def update(self, job: DownloadJob) -> DownloadJob: ...

    def delete(self, job_id: UUID) -> None: ...


class JobQueue(Protocol):
    def enqueue_download(self, job_id: UUID) -> None: ...


class VideoProvider(Protocol):
    def get_metadata(self, source_url: str) -> VideoMetadata: ...

    def download_best(self, source_url: str, output_dir: Path) -> DownloadResult: ...

    def search(self, query: str, limit: int) -> list[VideoSearchResult]: ...


class CaptionGenerator(Protocol):
    def generate(self, metadata: VideoMetadata, model: str | None = None) -> TikTokCaption: ...


class TrendsProvider(Protocol):
    def get_trending(self, region: str, max_results: int) -> list[TrendingVideo]: ...


class MediaProcessor(Protocol):
    def clip(self, input_path: Path, clip_range: ClipRange, output_path: Path) -> Path: ...


class FileStorage(Protocol):
    def prepare_download_path(self, job: DownloadJob) -> Path: ...

    def prepare_clip_path(self, job: DownloadJob, source_path: Path) -> Path: ...

    def cleanup_download_path(self, job: DownloadJob) -> None: ...

    def resolve(self, relative_path: str) -> Path: ...
