from functools import lru_cache
from typing import Literal, Optional

from pydantic import AnyUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    # App settings
    APP_NAME: str = Field(default="learn-system")
    ENV: Literal["local", "dev", "prod", "test"] = Field(default="local")
    DEBUG: bool = Field(default=True)
    API_STR: str = Field(default="/api")

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/learn_system",
        description="SQLAlchemy database URL",
    )

@lru_cache()
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
