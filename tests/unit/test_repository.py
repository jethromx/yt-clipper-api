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
