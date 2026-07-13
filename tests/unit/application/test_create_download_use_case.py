from uuid import UUID

import pytest

from yt_clipper.application.use_cases import CreateDownloadCommand, CreateDownloadUseCase
from yt_clipper.domain.exceptions import InvalidClipRangeError
from yt_clipper.domain.video import DownloadJob


class FakeRepository:
    def __init__(self) -> None:
        self.jobs: dict[UUID, DownloadJob] = {}

    def add(self, job: DownloadJob) -> DownloadJob:
        self.jobs[job.id] = job
        return job

    def get(self, job_id: UUID) -> DownloadJob | None:
        return self.jobs.get(job_id)

    def update(self, job: DownloadJob) -> DownloadJob:
        self.jobs[job.id] = job
        return job


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[UUID] = []

    def enqueue_download(self, job_id: UUID) -> None:
        self.enqueued.append(job_id)


def test_create_download_creates_and_enqueues_full_video_job() -> None:
    repository = FakeRepository()
    queue = FakeQueue()
    use_case = CreateDownloadUseCase(repository, queue)

    job = use_case.execute(
        CreateDownloadCommand(source_url="https://www.youtube.com/watch?v=abc123")
    )

    assert repository.get(job.id) == job
    assert queue.enqueued == [job.id]
    assert job.clip_range is None


def test_create_download_creates_clip_job() -> None:
    use_case = CreateDownloadUseCase(FakeRepository(), FakeQueue())

    job = use_case.execute(
        CreateDownloadCommand(
            source_url="https://www.youtube.com/watch?v=abc123",
            start_seconds=5,
            end_seconds=9,
        )
    )

    assert job.clip_range is not None
    assert job.clip_range.duration_seconds == 4


def test_create_download_requires_complete_clip_bounds() -> None:
    use_case = CreateDownloadUseCase(FakeRepository(), FakeQueue())

    with pytest.raises(InvalidClipRangeError):
        use_case.execute(
            CreateDownloadCommand(
                source_url="https://www.youtube.com/watch?v=abc123",
                start_seconds=5,
            )
        )
