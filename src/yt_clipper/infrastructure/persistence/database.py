from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from yt_clipper.config import Settings, get_settings


def create_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    current_settings = settings or get_settings()
    engine = create_engine(current_settings.database_url, pool_pre_ping=True)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


SessionLocal = create_session_factory()


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
