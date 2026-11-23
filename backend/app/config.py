"""Application settings, loaded from environment variables (see .env.example)."""

from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SESSION_SECRET = "dev-only-session-secret-not-for-deployment"  # noqa: S105
MIN_SESSION_SECRET_BYTES = 32
MIN_CRON_SECRET_BYTES = 32


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
    llm_enabled: bool = False  # off until the Limited Use review and vendor data terms are done
    anthropic_api_key: SecretStr = SecretStr("")
    llm_model: str = "claude-haiku-5-5"
    llm_daily_cap_per_user: int = Field(default=50, ge=0)
    llm_monthly_call_budget: int = Field(default=5000, ge=0)
    llm_rejection_threshold: float = Field(default=0.9, ge=0, le=1)
    llm_offer_interview_threshold: float = Field(default=0.85, ge=0, le=1)
    llm_timeout_seconds: float = Field(default=10.0, gt=0)
    sync_lease_minutes: int = Field(default=15, ge=1)
    followup_daily_draft_cap: int = Field(default=5, ge=1)
    followup_stale_days: int = Field(default=3, ge=0)
    ghosted_after_days: int = Field(default=21, ge=1)
    scheduler_lease_minutes: int = Field(default=15, ge=1)
    # "daily": drafts on any local weekday at run time (one job run a day). "window": only
    # weekdays 09:00-11:00 local (needs several runs a day).
    followup_window_mode: Literal["window", "daily"] = "daily"
    cron_secret: SecretStr = SecretStr("")
    cron_time_budget_seconds: float = Field(default=240.0, gt=30)
    # A user synced (e.g. by "Sync now") within this many hours is skipped by the daily job.
    sync_min_gap_hours: float = Field(default=12.0, ge=0)
    manual_sync_budget_seconds: float = Field(default=25.0, gt=0)
    # "serverless": no pooling in the app, no prepared statements (transaction-mode pooler).
    db_pool_mode: Literal["pooled", "serverless"] = "pooled"
    default_timezone: str = "America/Toronto"
    # None: the digest goes out whenever the daily job runs. A number restores "only after that
    # local hour" for deployments that run the job more than once a day.
    digest_send_after_local_hour: int | None = Field(default=None, ge=0, le=23)
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
    google_revoke_endpoint: str = "https://oauth2.googleapis.com/revoke"
    google_connect_redirect_uri: str = ""
    allowlist_emails: str = ""
    invite_hold_minutes: int = Field(default=10, ge=1)  # a code entered in a browser is held
    invite_claim_hours: int = Field(default=24, ge=1)  # a new account has this long to finish
    trusted_proxy_count: int = Field(default=0, ge=0)
    oauth_cookie_name: str = "tracker_oauth"
    invite_cookie_name: str = "tracker_invite"
    connect_cookie_name: str = "tracker_connect"

    @field_validator("database_url")
    @classmethod
    def _use_psycopg_driver(cls, url: str) -> str:
        """Hosted Postgres gives `postgres://` or `postgresql://`; SQLAlchemy needs the driver."""
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix) :]
        return url

    @property
    def llm_active(self) -> bool:
        """The kill switch is on only when explicitly enabled and a key exists."""
        return self.llm_enabled and bool(self.anthropic_api_key.get_secret_value())

    @property
    def google_configured(self) -> bool:
        return bool(
            self.google_client_id
            and self.google_client_secret.get_secret_value()
            and self.google_redirect_uri
        )

    @property
    def connect_redirect_uri(self) -> str:
        """The registered Gmail-connect redirect: explicit, else `/gmail/callback` on the same
        origin as the sign-in redirect URI."""
        if self.google_connect_redirect_uri:
            return self.google_connect_redirect_uri
        parts = urlparse(self.google_redirect_uri)
        return parts._replace(path="/gmail/callback", query="", fragment="").geturl()

    @property
    def allowlist(self) -> frozenset[str]:
        parts = (part.strip().lower() for part in self.allowlist_emails.split(","))
        return frozenset(part for part in parts if part)

    @property
    def oauth_cookie(self) -> str:
        return f"{self._cookie_prefix}{self.oauth_cookie_name}"

    @property
    def connect_cookie(self) -> str:
        return f"{self._cookie_prefix}{self.connect_cookie_name}"

    @property
    def invite_cookie(self) -> str:
        return f"{self._cookie_prefix}{self.invite_cookie_name}"

    @property
    def session_cookie(self) -> str:
        return f"{self._cookie_prefix}{self.session_cookie_name}"

    @property
    def csrf_cookie(self) -> str:
        """The only cookie that may carry a Domain (the app origin must read it): `__Host-` only
        when it is host-only, i.e. outside local with no cookie domain."""
        host_only = self.environment != "local" and self.cookie_domain is None
        name = self.csrf_cookie_name
        if self.cookie_domain is not None and self.environment == "staging":
            name = f"{name}_staging"  # staging and prod share the parent domain: no collision
        return f"{'__Host-' if host_only else ''}{name}"

    @property
    def _cookie_prefix(self) -> str:
        """`__Host-` (Secure, Path=/, no Domain) outside local, for every host-only cookie."""
        return "__Host-" if self.environment != "local" else ""

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
    def _check_cron_secret(self) -> "Settings":
        """The cron endpoint is public: outside local it needs a real secret."""
        if (
            self.environment != "local"
            and len(self.cron_secret.get_secret_value().encode()) < MIN_CRON_SECRET_BYTES
        ):
            raise ConfigError(f"CRON_SECRET must be set and at least {MIN_CRON_SECRET_BYTES} bytes")
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
