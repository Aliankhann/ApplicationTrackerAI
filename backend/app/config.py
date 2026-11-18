"""Application settings, loaded from environment variables (see .env.example)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["local", "staging", "prod"] = "local"
    database_url: str = "postgresql+psycopg://tracker:tracker@localhost:5432/tracker"
    frontend_origin: str = "http://localhost:5173"
    log_level: str = "INFO"
    max_users: int = 100
    token_encryption_keys: SecretStr = SecretStr("")
    token_encryption_current_version: str = ""
    classifier_review_threshold: float = Field(default=0.7, ge=0, le=1)
    sync_lease_minutes: int = Field(default=15, ge=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
