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
