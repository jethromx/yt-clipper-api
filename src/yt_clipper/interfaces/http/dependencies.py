from collections.abc import Iterator
from pathlib import Path

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from yt_clipper.application.ports import CaptionGenerator
from yt_clipper.application.use_cases import (
    CreateDownloadBatchUseCase,
    CreateDownloadUseCase,
    DeleteDownloadUseCase,
    GenerateTikTokCaptionUseCase,
    GetDownloadUseCase,
    SearchVideosUseCase,
)
from yt_clipper.config import Settings, get_settings
from yt_clipper.infrastructure.ai.anthropic_caption import (
    AnthropicCaptionGenerator,
    UnavailableCaptionGenerator,
)
from yt_clipper.infrastructure.persistence.database import get_session
from yt_clipper.infrastructure.persistence.repositories import SqlAlchemyDownloadJobRepository
from yt_clipper.infrastructure.queue.celery_queue import CeleryJobQueue
from yt_clipper.infrastructure.storage.local import LocalFileStorage
from yt_clipper.infrastructure.youtube.ytdlp_provider import YtDlpVideoProvider


def require_api_key(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    token = x_api_key
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if token not in settings.api_keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )


def get_download_repository(
    session: Session = Depends(get_session),
) -> SqlAlchemyDownloadJobRepository:
    return SqlAlchemyDownloadJobRepository(session)


def get_create_download_use_case(
    repository: SqlAlchemyDownloadJobRepository = Depends(get_download_repository),
) -> CreateDownloadUseCase:
    return CreateDownloadUseCase(repository, CeleryJobQueue())


def get_get_download_use_case(
    repository: SqlAlchemyDownloadJobRepository = Depends(get_download_repository),
) -> GetDownloadUseCase:
    return GetDownloadUseCase(repository)


def configured_storage_dir(settings: Settings = Depends(get_settings)) -> Path:
    return settings.storage_dir


def session_scope() -> Iterator[Session]:
    yield from get_session()


def get_video_provider(settings: Settings = Depends(get_settings)) -> YtDlpVideoProvider:
    return YtDlpVideoProvider(settings.ytdlp_socket_timeout_seconds)


def get_search_use_case(
    provider: YtDlpVideoProvider = Depends(get_video_provider),
) -> SearchVideosUseCase:
    return SearchVideosUseCase(provider)


def get_create_download_batch_use_case(
    repository: SqlAlchemyDownloadJobRepository = Depends(get_download_repository),
) -> CreateDownloadBatchUseCase:
    return CreateDownloadBatchUseCase(repository, CeleryJobQueue())


def get_caption_generator(settings: Settings = Depends(get_settings)) -> CaptionGenerator:
    if not settings.anthropic_api_key:
        return UnavailableCaptionGenerator()
    return AnthropicCaptionGenerator(
        model=settings.anthropic_model,
        api_key=settings.anthropic_api_key,
    )


def get_generate_caption_use_case(
    repository: SqlAlchemyDownloadJobRepository = Depends(get_download_repository),
    generator: CaptionGenerator = Depends(get_caption_generator),
) -> GenerateTikTokCaptionUseCase:
    return GenerateTikTokCaptionUseCase(repository, generator)


def get_file_storage(settings: Settings = Depends(get_settings)) -> LocalFileStorage:
    return LocalFileStorage(settings.storage_dir)


def get_delete_download_use_case(
    repository: SqlAlchemyDownloadJobRepository = Depends(get_download_repository),
    storage: LocalFileStorage = Depends(get_file_storage),
) -> DeleteDownloadUseCase:
    return DeleteDownloadUseCase(repository, storage)
