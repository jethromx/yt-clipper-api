from uuid import uuid4

from yt_clipper import worker


def test_worker_executes_download_job(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[str] = []

    class FakeSession:
        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, exc_type, exc, traceback):  # type: ignore[no-untyped-def]
            return None

    class FakeRepository:
        def __init__(self, session):  # type: ignore[no-untyped-def]
            self.session = session

    class FakeUseCase:
        def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
            self.kwargs = kwargs

        def execute(self, job_id):  # type: ignore[no-untyped-def]
            calls.append(str(job_id))

            class Job:
                id = job_id

            return Job()

    monkeypatch.setattr(worker, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(worker, "SqlAlchemyDownloadJobRepository", FakeRepository)
    monkeypatch.setattr(worker, "ExecuteDownloadJobUseCase", FakeUseCase)
    # Hermetic: avoid LocalFileStorage touching the real filesystem (STORAGE_DIR
    # may point at a read-only path like /app/downloads via a local .env).
    monkeypatch.setattr(worker, "LocalFileStorage", lambda root: object())
    job_id = uuid4()

    result = worker.execute_download_job.run(str(job_id))

    assert result == str(job_id)
    assert calls == [str(job_id)]
