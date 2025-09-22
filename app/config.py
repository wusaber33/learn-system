from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = Field(default="learn-system")
    ENV: str = Field(default="local")
    DEBUG: bool = Field(default=True)
    API_STR: str = Field(default="/api")
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:secret@localhost:5432/learnsystem"
    )

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
