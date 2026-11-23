"""Vercel hosting: entry point, vercel.json, requirements.txt freshness, settings, engine."""

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy.pool import NullPool

from app.api.deps import CRON_ROUTES
from app.config import ConfigError, Settings
from app.db import build_engine

BACKEND = Path(__file__).parents[1]
PROD = {"ENVIRONMENT": "prod", "SESSION_SECRET": "s" * 40, "CRON_SECRET": "c" * 40}


def settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    for key, value in {**PROD, **env}.items():
        monkeypatch.setenv(key, value)
    return Settings()


# ---------- settings validation ----------


@pytest.mark.parametrize("secret", ["", "short", "x" * 31])
def test_cron_secret_is_required_outside_local_at_32_bytes(
    monkeypatch: pytest.MonkeyPatch, secret: str
) -> None:
    with pytest.raises(ConfigError, match="CRON_SECRET"):
        settings(monkeypatch, CRON_SECRET=secret)
    assert settings(monkeypatch, CRON_SECRET="x" * 32).cron_secret.get_secret_value() == "x" * 32


def test_cron_secret_is_optional_locally_and_never_printed(monkeypatch: pytest.MonkeyPatch) -> None:
    local = settings(monkeypatch, ENVIRONMENT="local", CRON_SECRET="")
    assert local.cron_secret.get_secret_value() == ""
    assert "c" * 40 not in repr(settings(monkeypatch))


def test_api_base_url_must_be_https_outside_local(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ConfigError, match="API_BASE_URL"):
        settings(monkeypatch, API_BASE_URL="http://api.example.test")


def test_db_pool_mode_is_validated_and_defaults_to_pooled(monkeypatch: pytest.MonkeyPatch) -> None:
    assert settings(monkeypatch).db_pool_mode == "pooled"
    assert settings(monkeypatch, DB_POOL_MODE="serverless").db_pool_mode == "serverless"
    with pytest.raises(ValidationError):
        settings(monkeypatch, DB_POOL_MODE="pgbouncer")


def test_daily_schedule_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FOLLOWUP_WINDOW_MODE")
    monkeypatch.delenv("DIGEST_SEND_AFTER_LOCAL_HOUR")
    configured = settings(monkeypatch)
    assert configured.followup_window_mode == "daily"
    assert configured.digest_send_after_local_hour is None
    assert configured.sync_min_gap_hours == 12
    assert (configured.cron_time_budget_seconds, configured.manual_sync_budget_seconds) == (240, 25)


@pytest.mark.parametrize("raw", ["postgres://u:p@h/db", "postgresql://u:p@h/db"])
def test_hosted_postgres_urls_get_the_psycopg_driver(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    assert settings(monkeypatch, DATABASE_URL=raw).database_url == "postgresql+psycopg://u:p@h/db"
    explicit = "postgresql+psycopg://u:p@h/db"
    assert settings(monkeypatch, DATABASE_URL=explicit).database_url == explicit


# ---------- serverless engine ----------


def test_serverless_engine_uses_nullpool_and_no_prepared_statements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = build_engine(settings(monkeypatch, DB_POOL_MODE="serverless"))
    assert isinstance(engine.pool, NullPool)
    captured: dict[str, object] = {}
    import app.db as db

    def fake_create(url: str, **kwargs: object) -> object:
        captured.update(kwargs)
        return engine

    monkeypatch.setattr(db, "create_engine", fake_create)
    build_engine(settings(monkeypatch, DB_POOL_MODE="serverless"))
    assert captured["poolclass"] is NullPool
    assert captured["connect_args"] == {"prepare_threshold": None}


def test_pooled_engine_keeps_the_default_pool_with_pre_ping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = build_engine(settings(monkeypatch))
    assert not isinstance(engine.pool, NullPool)
    assert engine.pool._pre_ping is True


# ---------- Vercel files ----------


def test_api_index_exposes_the_asgi_app() -> None:
    spec = importlib.util.spec_from_file_location("vercel_entry", BACKEND / "api/index.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from app.main import app

    assert module.app is app


def test_backend_vercel_json_routes_everything_to_the_function_with_one_daily_cron() -> None:
    config = json.loads((BACKEND / "vercel.json").read_text())
    assert config["rewrites"] == [{"source": "/(.*)", "destination": "/api/index"}]
    assert config["functions"]["api/index.py"]["maxDuration"] == 300
    (cron,) = config["crons"]
    assert cron == {"path": "/internal/cron/tick", "schedule": "0 12 * * *"}
    assert ("GET", cron["path"]) in CRON_ROUTES
    minute, hour, *rest = cron["schedule"].split()
    assert minute.isdigit() and hour.isdigit() and rest == ["*", "*", "*"]  # once a day


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not installed")
def test_requirements_txt_matches_uv_lock() -> None:
    """Vercel installs from requirements.txt; regenerate with the command in its header."""
    exported = subprocess.run(
        [  # noqa: S607
            "uv",
            "export",
            "--no-dev",
            "--no-hashes",
            "--locked",
            "--no-emit-project",
        ],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    committed = (BACKEND / "requirements.txt").read_text()
    assert committed == exported, (
        "backend/requirements.txt is stale; run: uv export --no-dev --no-hashes --locked "
        "--no-emit-project > requirements.txt"
    )
