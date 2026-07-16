from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, model_validator

from yt_clipper.domain.video import DownloadJob, DownloadStatus, VideoSearchResult


class CreateDownloadRequest(BaseModel):
    source_url: HttpUrl
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_clip_bounds(self) -> "CreateDownloadRequest":
        if (self.start_seconds is None) != (self.end_seconds is None):
            raise ValueError("start_seconds and end_seconds must be provided together")
        return self


class DownloadJobResponse(BaseModel):
    id: UUID
    source_url: str
    status: DownloadStatus
    start_seconds: float | None
    end_seconds: float | None
    output_path: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    video_title: str | None
    video_description: str | None
    youtube_tags: list[str]
    tiktok_caption: str | None
    tiktok_hashtags: list[str]
    tiktok_generated_at: datetime | None

    @classmethod
    def from_domain(cls, job: DownloadJob) -> "DownloadJobResponse":
        return cls(
            id=job.id,
            source_url=job.source_url,
            status=job.status,
            start_seconds=job.clip_range.start_seconds if job.clip_range else None,
            end_seconds=job.clip_range.end_seconds if job.clip_range else None,
            output_path=job.output_path,
            error_message=job.error_message,
            created_at=job.created_at,
            updated_at=job.updated_at,
            video_title=job.video_title,
            video_description=job.video_description,
            youtube_tags=list(job.youtube_tags),
            tiktok_caption=job.tiktok_caption,
            tiktok_hashtags=list(job.tiktok_hashtags),
            tiktok_generated_at=job.tiktok_generated_at,
        )


class BatchDownloadRequest(BaseModel):
    source_urls: list[HttpUrl] = Field(min_length=1, max_length=50)


class BatchDownloadResponse(BaseModel):
    jobs: list[DownloadJobResponse]


class SearchResultResponse(BaseModel):
    video_id: str
    title: str
    url: str
    duration_seconds: float | None
    channel: str | None
    thumbnail_url: str | None

    @classmethod
    def from_domain(cls, result: VideoSearchResult) -> "SearchResultResponse":
        return cls(
            video_id=result.video_id,
            title=result.title,
            url=result.url,
            duration_seconds=result.duration_seconds,
            channel=result.channel,
            thumbnail_url=result.thumbnail_url,
        )


class SearchResponse(BaseModel):
    results: list[SearchResultResponse]


class GenerateCaptionRequest(BaseModel):
    model: str | None = None


class ModelsResponse(BaseModel):
    models: list[str]
    default: str


class SuggestionResponse(BaseModel):
    text: str
    kind: str


class SuggestionsResponse(BaseModel):
    suggestions: list[SuggestionResponse]
