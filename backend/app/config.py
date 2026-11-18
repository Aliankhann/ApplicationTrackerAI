"""Application settings, loaded from environment variables (see .env.example)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SESSION_SECRET = "dev-only-session-secret-not-for-deployment"  # noqa: S105
MIN_SESSION_SECRET_BYTES = 32


class ConfigError(Exception):
    """Invalid configuration. Messages never contain secret values."""


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
    followup_daily_draft_cap: int = Field(default=5, ge=1)
    followup_stale_days: int = Field(default=3, ge=0)
    ghosted_after_days: int = Field(default=21, ge=1)
    scheduler_lease_minutes: int = Field(default=15, ge=1)
    default_timezone: str = "America/Toronto"
    session_cookie_name: str = "tracker_session"
    csrf_cookie_name: str = "tracker_csrf"
    session_absolute_days: int = Field(default=14, ge=1)
    session_idle_hours: int = Field(default=72, ge=1)
    cookie_domain: str | None = None
    session_secret: SecretStr = SecretStr("")

    @property
    def session_cookie(self) -> str:
        return f"{self._cookie_prefix}{self.session_cookie_name}"

    @property
    def csrf_cookie(self) -> str:
        return f"{self._cookie_prefix}{self.csrf_cookie_name}"

    @property
    def _cookie_prefix(self) -> str:
        """`__Host-` (Secure, Path=/, no Domain) whenever that is possible."""
        return "__Host-" if self.environment != "local" and self.cookie_domain is None else ""

    @model_validator(mode="after")
    def _check_session_secret(self) -> "Settings":
        secret = self.session_secret.get_secret_value()
        if self.environment == "local" and not secret:
            self.session_secret = SecretStr(DEV_SESSION_SECRET)
        elif len(secret.encode()) < MIN_SESSION_SECRET_BYTES:
            raise ConfigError(
                f"SESSION_SECRET must be set and at least {MIN_SESSION_SECRET_BYTES} bytes"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
