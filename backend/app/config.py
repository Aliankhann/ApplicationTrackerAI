"""Application settings, loaded from environment variables (see .env.example)."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["local", "staging", "prod"] = "local"
    database_url: str = "postgresql+psycopg://tracker:tracker@localhost:5432/tracker"
    frontend_origin: str = "http://localhost:5173"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
