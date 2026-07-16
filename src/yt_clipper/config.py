from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "yt-clipper-api"
    environment: str = "local"
    api_keys: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["dev-secret-change-me"]
    )
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )
    database_url: str = "sqlite:///./yt_clipper.db"
    redis_url: str = "redis://localhost:6379/0"
    storage_dir: Path = Path("downloads")
    max_clip_duration_seconds: int = 14_400
    ytdlp_socket_timeout_seconds: int = 30
    ffmpeg_timeout_seconds: int = 1_800
    celery_task_always_eager: bool = False
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-haiku-4-5"
    anthropic_allowed_models: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "claude-haiku-4-5",
            "claude-sonnet-5",
            "claude-opus-4-8",
        ]
    )
    youtube_api_key: str | None = None
    trends_region: str = "MX"
    trends_cache_ttl_seconds: int = 3600

    @field_validator("api_keys", "cors_origins", "anthropic_allowed_models", mode="before")
    @classmethod
    def split_csv(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
