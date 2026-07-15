from uuid import uuid4

from yt_clipper.application.use_cases import DeleteDownloadUseCase
from yt_clipper.domain.video import DownloadJob


class FakeRepository:
    def __init__(self, job: DownloadJob | None = None) -> None:
        self.jobs = {job.id: job} if job else {}
        self.deleted: list = []

    def add(self, job):
        self.jobs[job.id] = job
        return job

    def get(self, job_id):
        return self.jobs.get(job_id)

    def update(self, job):
        self.jobs[job.id] = job
        return job

    def delete(self, job_id) -> None:
        self.deleted.append(job_id)
        self.jobs.pop(job_id, None)


class FakeStorage:
    def __init__(self) -> None:
        self.cleaned: list = []

    def cleanup_download_path(self, job) -> None:
        self.cleaned.append(job.id)


def test_delete_removes_files_and_record() -> None:
    job = DownloadJob(source_url="https://youtu.be/abc")
    repository = FakeRepository(job)
    storage = FakeStorage()

    DeleteDownloadUseCase(repository, storage).execute(job.id)

    assert storage.cleaned == [job.id]
    assert repository.deleted == [job.id]


def test_delete_missing_job_is_noop() -> None:
    repository = FakeRepository()
    storage = FakeStorage()

    DeleteDownloadUseCase(repository, storage).execute(uuid4())

    assert storage.cleaned == []
    assert repository.deleted == []
