from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, model_validator

from yt_clipper.domain.video import DownloadJob, DownloadStatus


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
        )
