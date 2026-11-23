from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import get_settings
from app.security.crypto import clear_keyring_cache


@pytest.fixture(autouse=True)
def _public_api_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-local environments require a public https API_BASE_URL."""
    monkeypatch.setenv("API_BASE_URL", "https://api.example.test")


@pytest.fixture(autouse=True)
def _cron_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-local environments require a CRON_SECRET of at least 32 bytes."""
    monkeypatch.setenv("CRON_SECRET", "c" * 40)


@pytest.fixture(autouse=True)
def _time_of_day_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    """The suite's fixtures assume the multi-run-a-day rules (9-11 am drafts, digest after 8:00);
    daily-mode tests override these."""
    monkeypatch.setenv("FOLLOWUP_WINDOW_MODE", "window")
    monkeypatch.setenv("DIGEST_SEND_AFTER_LOCAL_HOUR", "8")


@pytest.fixture(autouse=True)
def _clear_caches() -> Iterator[None]:
    get_settings.cache_clear()
    clear_keyring_cache()
    yield
    get_settings.cache_clear()
    clear_keyring_cache()


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(get_settings().database_url)
    connection = engine.connect()
    outer = connection.begin()
    session = Session(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()
        engine.dispose()
