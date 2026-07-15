from uuid import UUID

import pytest

from yt_clipper.application.use_cases import (
    CreateDownloadBatchUseCase,
    SearchVideosUseCase,
)
from yt_clipper.domain.exceptions import (
    BatchTooLargeError,
    EmptyBatchError,
    EmptySearchQueryError,
)
from yt_clipper.domain.video import DownloadJob, VideoSearchResult


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


class FakeSearchProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, limit: int) -> list[VideoSearchResult]:
        self.calls.append((query, limit))
        return [VideoSearchResult(video_id="abc", title="t", url="u")]


def test_search_clamps_limit_and_delegates() -> None:
    provider = FakeSearchProvider()
    use_case = SearchVideosUseCase(provider)

    results = use_case.execute("perros", limit=999)

    assert provider.calls == [("perros", 50)]
    assert len(results) == 1


def test_search_rejects_empty_query() -> None:
    with pytest.raises(EmptySearchQueryError):
        SearchVideosUseCase(FakeSearchProvider()).execute("   ", limit=10)


def test_batch_creates_and_enqueues_jobs() -> None:
    repository = FakeRepository()
    queue = FakeQueue()
    use_case = CreateDownloadBatchUseCase(repository, queue)

    jobs = use_case.execute(["https://youtu.be/a", "https://youtu.be/b"])

    assert len(jobs) == 2
    assert len(queue.enqueued) == 2
    assert all(job.clip_range is None for job in jobs)


def test_batch_rejects_empty_list() -> None:
    with pytest.raises(EmptyBatchError):
        CreateDownloadBatchUseCase(FakeRepository(), FakeQueue()).execute([])


def test_batch_rejects_oversized_list() -> None:
    urls = [f"https://youtu.be/{i}" for i in range(51)]
    with pytest.raises(BatchTooLargeError):
        CreateDownloadBatchUseCase(FakeRepository(), FakeQueue()).execute(urls)
