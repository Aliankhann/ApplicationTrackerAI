"""Application settings, loaded from environment variables (see .env.example)."""

from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

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
    api_base_url: str = "http://localhost:8000"
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
    digest_hour: int = Field(default=8, ge=0, le=23)
    digest_unsubscribe_days: int = Field(default=60, ge=1)
    session_cookie_name: str = "tracker_session"
    csrf_cookie_name: str = "tracker_csrf"
    session_absolute_days: int = Field(default=14, ge=1)
    session_idle_hours: int = Field(default=72, ge=1)
    cookie_domain: str | None = None
    session_secret: SecretStr = SecretStr("")
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    google_redirect_uri: str = ""
    google_issuer: str = "https://accounts.google.com"
    google_authorization_endpoint: str = "https://accounts.google.com/o/oauth2/v2/auth"
    google_token_endpoint: str = "https://oauth2.googleapis.com/token"  # noqa: S105
    google_jwks_uri: str = "https://www.googleapis.com/oauth2/v3/certs"
    allowlist_emails: str = ""
    trusted_proxy_count: int = Field(default=0, ge=0)
    oauth_cookie_name: str = "tracker_oauth"
    invite_cookie_name: str = "tracker_invite"

    @property
    def google_configured(self) -> bool:
        return bool(
            self.google_client_id
            and self.google_client_secret.get_secret_value()
            and self.google_redirect_uri
        )

    @property
    def allowlist(self) -> frozenset[str]:
        parts = (part.strip().lower() for part in self.allowlist_emails.split(","))
        return frozenset(part for part in parts if part)

    @property
    def oauth_cookie(self) -> str:
        return f"{self._cookie_prefix}{self.oauth_cookie_name}"

    @property
    def invite_cookie(self) -> str:
        return f"{self._cookie_prefix}{self.invite_cookie_name}"

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

    @model_validator(mode="after")
    def _check_api_base_url(self) -> "Settings":
        """Unsubscribe links must be public https URLs outside local."""
        if self.environment != "local":
            url = urlparse(self.api_base_url)
            if url.scheme != "https" or url.hostname in (None, "localhost", "127.0.0.1", "::1"):
                raise ConfigError("API_BASE_URL must be a public https URL outside local")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
