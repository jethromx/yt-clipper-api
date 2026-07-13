from uuid import UUID

from celery import Celery

from yt_clipper.application.use_cases import ExecuteDownloadJobUseCase
from yt_clipper.config import get_settings
from yt_clipper.infrastructure.media.ffmpeg_processor import FfmpegMediaProcessor
from yt_clipper.infrastructure.persistence.database import SessionLocal
from yt_clipper.infrastructure.persistence.repositories import SqlAlchemyDownloadJobRepository
from yt_clipper.infrastructure.storage.local import LocalFileStorage
from yt_clipper.infrastructure.youtube.ytdlp_provider import YtDlpVideoProvider

settings = get_settings()
celery_app = Celery("yt_clipper", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.task_always_eager = settings.celery_task_always_eager


@celery_app.task(name="yt_clipper.execute_download_job")  # type: ignore[untyped-decorator]
def execute_download_job(job_id: str) -> str:
    with SessionLocal() as session:
        repository = SqlAlchemyDownloadJobRepository(session)
        use_case = ExecuteDownloadJobUseCase(
            repository=repository,
            video_provider=YtDlpVideoProvider(settings.ytdlp_socket_timeout_seconds),
            media_processor=FfmpegMediaProcessor(settings.ffmpeg_timeout_seconds),
            storage=LocalFileStorage(settings.storage_dir),
        )
        job = use_case.execute(UUID(job_id))
        return str(job.id)
