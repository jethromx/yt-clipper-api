from uuid import UUID

from yt_clipper.worker import execute_download_job


class CeleryJobQueue:
    def enqueue_download(self, job_id: UUID) -> None:
        execute_download_job.delay(str(job_id))
