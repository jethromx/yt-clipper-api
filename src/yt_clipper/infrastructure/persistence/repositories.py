from uuid import UUID

from sqlalchemy.orm import Session

from yt_clipper.domain.video import ClipRange, DownloadJob, DownloadStatus
from yt_clipper.infrastructure.persistence.models import DownloadJobRecord


class SqlAlchemyDownloadJobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, job: DownloadJob) -> DownloadJob:
        self.session.add(self._to_record(job))
        self.session.commit()
        return job

    def get(self, job_id: UUID) -> DownloadJob | None:
        record = self.session.get(DownloadJobRecord, str(job_id))
        if record is None:
            return None
        return self._to_domain(record)

    def update(self, job: DownloadJob) -> DownloadJob:
        record = self.session.get(DownloadJobRecord, str(job.id))
        if record is None:
            record = self._to_record(job)
            self.session.add(record)
        else:
            self._sync_record(record, job)
        self.session.commit()
        return job

    @staticmethod
    def _to_record(job: DownloadJob) -> DownloadJobRecord:
        record = DownloadJobRecord()
        SqlAlchemyDownloadJobRepository._sync_record(record, job)
        return record

    @staticmethod
    def _sync_record(record: DownloadJobRecord, job: DownloadJob) -> None:
        record.id = str(job.id)
        record.source_url = job.source_url
        record.status = job.status.value
        record.start_seconds = job.clip_range.start_seconds if job.clip_range else None
        record.end_seconds = job.clip_range.end_seconds if job.clip_range else None
        record.output_path = job.output_path
        record.error_message = job.error_message
        record.created_at = job.created_at
        record.updated_at = job.updated_at
        record.video_title = job.video_title
        record.video_description = job.video_description
        record.youtube_tags = list(job.youtube_tags)
        record.tiktok_caption = job.tiktok_caption
        record.tiktok_hashtags = list(job.tiktok_hashtags)
        record.tiktok_generated_at = job.tiktok_generated_at

    @staticmethod
    def _to_domain(record: DownloadJobRecord) -> DownloadJob:
        clip_range = None
        if record.start_seconds is not None and record.end_seconds is not None:
            clip_range = ClipRange(record.start_seconds, record.end_seconds)
        return DownloadJob(
            id=UUID(record.id),
            source_url=record.source_url,
            clip_range=clip_range,
            status=DownloadStatus(record.status),
            output_path=record.output_path,
            error_message=record.error_message,
            created_at=record.created_at,
            updated_at=record.updated_at,
            video_title=record.video_title,
            video_description=record.video_description,
            youtube_tags=list(record.youtube_tags or []),
            tiktok_caption=record.tiktok_caption,
            tiktok_hashtags=list(record.tiktok_hashtags or []),
            tiktok_generated_at=record.tiktok_generated_at,
        )
