from collections.abc import Iterator
from pathlib import Path

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from yt_clipper.application.use_cases import CreateDownloadUseCase, GetDownloadUseCase
from yt_clipper.config import Settings, get_settings
from yt_clipper.infrastructure.persistence.database import get_session
from yt_clipper.infrastructure.persistence.repositories import SqlAlchemyDownloadJobRepository
from yt_clipper.infrastructure.queue.celery_queue import CeleryJobQueue


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
