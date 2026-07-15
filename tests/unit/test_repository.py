from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from yt_clipper.domain.video import ClipRange, DownloadJob, DownloadStatus
from yt_clipper.infrastructure.persistence.models import Base
from yt_clipper.infrastructure.persistence.repositories import SqlAlchemyDownloadJobRepository


def test_repository_add_get_and_update_roundtrip() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        repository = SqlAlchemyDownloadJobRepository(session)
        job = DownloadJob(
            source_url="https://www.youtube.com/watch?v=abc123",
            clip_range=ClipRange(1, 4),
        )

        repository.add(job)
        loaded = repository.get(job.id)

        assert loaded is not None
        assert loaded.id == job.id
        assert loaded.clip_range is not None
        assert loaded.clip_range.duration_seconds == 3

        loaded.mark_completed("downloads/video.mp4")
        repository.update(loaded)

        updated = repository.get(job.id)
        assert updated is not None
        assert updated.status == DownloadStatus.COMPLETED
        assert updated.output_path == "downloads/video.mp4"


def test_repository_update_inserts_missing_job() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        repository = SqlAlchemyDownloadJobRepository(session)
        job = DownloadJob(source_url="https://www.youtube.com/watch?v=abc123")

        repository.update(job)

        assert repository.get(job.id) is not None


def test_repository_round_trips_metadata_and_tiktok() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        from yt_clipper.domain.video import DownloadJob, TikTokCaption, VideoMetadata
        from yt_clipper.infrastructure.persistence.repositories import (
            SqlAlchemyDownloadJobRepository,
        )

        repo = SqlAlchemyDownloadJobRepository(session)
        job = DownloadJob(source_url="https://youtu.be/abc")
        job.apply_metadata(VideoMetadata(video_id="abc", title="T", description="D", tags=["a"]))
        job.apply_tiktok_caption(TikTokCaption(caption="C", hashtags=["#a"]))
        repo.add(job)

        loaded = repo.get(job.id)

        assert loaded is not None
        assert loaded.video_title == "T"
        assert loaded.youtube_tags == ["a"]
        assert loaded.tiktok_caption == "C"
        assert loaded.tiktok_hashtags == ["#a"]
        assert loaded.tiktok_generated_at is not None
