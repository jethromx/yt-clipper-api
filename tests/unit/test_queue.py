from uuid import uuid4

from yt_clipper.infrastructure.queue import celery_queue
from yt_clipper.infrastructure.queue.celery_queue import CeleryJobQueue


def test_celery_queue_enqueues_download(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[str] = []

    class FakeTask:
        @staticmethod
        def delay(job_id: str) -> None:
            calls.append(job_id)

    monkeypatch.setattr(celery_queue, "execute_download_job", FakeTask)
    job_id = uuid4()

    CeleryJobQueue().enqueue_download(job_id)

    assert calls == [str(job_id)]
