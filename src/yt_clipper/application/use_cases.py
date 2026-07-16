from __future__ import annotations

import re
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from yt_clipper.application.ports import (
    CaptionGenerator,
    DownloadJobRepository,
    FileStorage,
    JobQueue,
    MediaProcessor,
    TrendsProvider,
    VideoProvider,
)
from yt_clipper.domain.exceptions import (
    BatchTooLargeError,
    CaptionNotAvailableError,
    DomainError,
    EmptyBatchError,
    EmptySearchQueryError,
    InvalidClipRangeError,
)
from yt_clipper.domain.trends import SearchSuggestion, TrendingVideo
from yt_clipper.domain.video import (
    ClipRange,
    DownloadJob,
    DownloadStatus,
    TikTokCaption,
    VideoMetadata,
    VideoSearchResult,
)


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
            result = self.video_provider.download_best(
                job.source_url,
                self.storage.prepare_download_path(job),
            )
            job.apply_metadata(result.metadata)
            output_path = self._clip_if_needed(job, result.path)
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


MAX_BATCH_SIZE = 50
MAX_SEARCH_LIMIT = 50
OVER_FETCH_FACTOR = 3


class SearchVideosUseCase:
    def __init__(self, video_provider: VideoProvider) -> None:
        self.video_provider = video_provider

    def execute(
        self, query: str, limit: int, max_duration_seconds: int | None = None
    ) -> list[VideoSearchResult]:
        if not query.strip():
            raise EmptySearchQueryError("query must not be empty")
        bounded = max(1, min(limit, MAX_SEARCH_LIMIT))
        if max_duration_seconds is None:
            return self.video_provider.search(query.strip(), bounded)
        fetch_limit = min(bounded * OVER_FETCH_FACTOR, MAX_SEARCH_LIMIT)
        results = self.video_provider.search(query.strip(), fetch_limit)
        filtered = [
            result
            for result in results
            if result.duration_seconds is not None
            and result.duration_seconds <= max_duration_seconds
        ]
        return filtered[:bounded]


class CreateDownloadBatchUseCase:
    def __init__(self, repository: DownloadJobRepository, queue: JobQueue) -> None:
        self.repository = repository
        self.queue = queue

    def execute(self, source_urls: list[str]) -> list[DownloadJob]:
        if not source_urls:
            raise EmptyBatchError("source_urls must not be empty")
        if len(source_urls) > MAX_BATCH_SIZE:
            raise BatchTooLargeError(f"batch exceeds {MAX_BATCH_SIZE} items")
        jobs: list[DownloadJob] = []
        for source_url in source_urls:
            job = DownloadJob(source_url=source_url)
            self.repository.add(job)
            self.queue.enqueue_download(job.id)
            jobs.append(job)
        return jobs


class GenerateTikTokCaptionUseCase:
    def __init__(
        self,
        repository: DownloadJobRepository,
        generator: CaptionGenerator,
    ) -> None:
        self.repository = repository
        self.generator = generator

    def execute(self, job_id: UUID, model: str | None = None) -> DownloadJob:
        job = self.repository.get(job_id)
        if job is None:
            raise DomainError(f"download job not found: {job_id}")
        if job.status != DownloadStatus.COMPLETED or not job.video_title:
            raise CaptionNotAvailableError("caption requires a completed job with video metadata")
        title = job.video_title  # narrowed to str by the guard above
        metadata = VideoMetadata(
            video_id="",
            title=title,
            description=job.video_description,
            tags=list(job.youtube_tags),
        )
        caption: TikTokCaption = self.generator.generate(metadata, model)
        job.apply_tiktok_caption(caption)
        self.repository.update(job)
        return job


class DeleteDownloadUseCase:
    def __init__(self, repository: DownloadJobRepository, storage: FileStorage) -> None:
        self.repository = repository
        self.storage = storage

    def execute(self, job_id: UUID) -> None:
        job = self.repository.get(job_id)
        if job is None:
            return
        self.storage.cleanup_download_path(job)
        self.repository.delete(job_id)


MAX_SUGGESTIONS = 30
TRENDING_FETCH_SIZE = 25
MAX_TAG_LENGTH = 30
_HASHTAG_RE = re.compile(r"#[\wÀ-ſ]+", re.UNICODE)


class GetSearchSuggestionsUseCase:
    def __init__(self, provider: TrendsProvider) -> None:
        self.provider = provider

    def execute(self, region: str, limit: int) -> list[SearchSuggestion]:
        bounded = max(1, min(limit, MAX_SUGGESTIONS))
        videos = self.provider.get_trending(region, TRENDING_FETCH_SIZE)
        suggestions: list[SearchSuggestion] = []
        seen: set[str] = set()
        for video in videos:
            for candidate in self._candidates(video):
                key = candidate.text.lower()
                if not candidate.text or key in seen:
                    continue
                seen.add(key)
                suggestions.append(candidate)
                if len(suggestions) >= bounded:
                    return suggestions
        return suggestions

    @staticmethod
    def _candidates(video: TrendingVideo) -> list[SearchSuggestion]:
        result = [
            SearchSuggestion(text=match, kind="hashtag")
            for match in _HASHTAG_RE.findall(video.title)
        ]
        result.extend(
            SearchSuggestion(text=tag, kind="topic")
            for tag in video.tags
            if tag and len(tag) <= MAX_TAG_LENGTH
        )
        return result
