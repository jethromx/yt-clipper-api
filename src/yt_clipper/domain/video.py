from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from yt_clipper.domain.exceptions import InvalidClipRangeError


class DownloadStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ClipRange:
    start_seconds: float
    end_seconds: float

    def __post_init__(self) -> None:
        if self.start_seconds < 0:
            raise InvalidClipRangeError("start_seconds must be greater than or equal to 0")
        if self.end_seconds <= self.start_seconds:
            raise InvalidClipRangeError("end_seconds must be greater than start_seconds")

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


@dataclass(frozen=True, slots=True)
class VideoMetadata:
    video_id: str
    title: str
    duration_seconds: float | None = None
    webpage_url: str | None = None
    description: str | None = None
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TikTokCaption:
    caption: str
    hashtags: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class VideoSearchResult:
    video_id: str
    title: str
    url: str
    duration_seconds: float | None = None
    channel: str | None = None
    thumbnail_url: str | None = None


@dataclass(slots=True)
class DownloadJob:
    source_url: str
    clip_range: ClipRange | None = None
    id: UUID = field(default_factory=uuid4)
    status: DownloadStatus = DownloadStatus.QUEUED
    output_path: str | None = None
    error_message: str | None = None
    video_title: str | None = None
    video_description: str | None = None
    youtube_tags: list[str] = field(default_factory=list)
    tiktok_caption: str | None = None
    tiktok_hashtags: list[str] = field(default_factory=list)
    tiktok_generated_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_clip(self) -> bool:
        return self.clip_range is not None

    def mark_running(self) -> None:
        self.status = DownloadStatus.RUNNING
        self.updated_at = datetime.now(UTC)

    def mark_completed(self, output_path: str) -> None:
        self.status = DownloadStatus.COMPLETED
        self.output_path = output_path
        self.error_message = None
        self.updated_at = datetime.now(UTC)

    def mark_failed(self, error_message: str) -> None:
        self.status = DownloadStatus.FAILED
        self.error_message = error_message
        self.updated_at = datetime.now(UTC)

    def apply_metadata(self, metadata: VideoMetadata) -> None:
        self.video_title = metadata.title
        self.video_description = metadata.description
        self.youtube_tags = list(metadata.tags)
        self.updated_at = datetime.now(UTC)

    def apply_tiktok_caption(self, caption: TikTokCaption) -> None:
        self.tiktok_caption = caption.caption
        self.tiktok_hashtags = list(caption.hashtags)
        self.tiktok_generated_at = datetime.now(UTC)
        self.updated_at = datetime.now(UTC)
