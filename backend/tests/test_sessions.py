import logging
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_clock
from app.config import ConfigError, Settings, get_settings
from app.db import get_db
from app.main import create_app
from app.models import User, UserSession
from app.security import sessions

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
SECRET = "x" * 40


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


class Env:
    def __init__(self, db: Session, clock: Clock, monkeypatch: pytest.MonkeyPatch) -> None:
        self.db = db
        self.clock = clock
        self.monkeypatch = monkeypatch
        monkeypatch.setenv("SESSION_SECRET", SECRET)
        get_settings.cache_clear()

    def app(self, environment: str = "local", **env: str) -> TestClient:
        self.monkeypatch.setenv("ENVIRONMENT", environment)
        for key, value in env.items():
            self.monkeypatch.setenv(key.upper(), value)
        get_settings.cache_clear()
        app = create_app()
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_clock] = lambda: self.clock
        return TestClient(app, base_url="http://testserver")

    def user(self, **kw: object) -> User:
        user = User(google_sub=uuid.uuid4().hex, email="u@example.test", **kw)
        self.db.add(user)
        self.db.flush()
        return user

    def login(self, user: User) -> tuple[str, str, UserSession]:
        return sessions.create_session(self.db, user.id, self.clock.now, get_settings())


@pytest.fixture
def env(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[Env]:
    yield Env(db_session, Clock(), monkeypatch)


def cookies(client: TestClient, raw: str, csrf: str) -> None:
    client.cookies.set("tracker_session", raw)
    client.cookies.set("tracker_csrf", csrf)


def test_cookie_flags_httponly_lax_secure_path_domain_and_readable_csrf(env: Env) -> None:
    from fastapi import FastAPI, Response

    from app.api.deps import set_session_cookies

    for environment, secure in (("local", False), ("prod", True)):
        env.app(environment, cookie_domain=".example.com")
        settings = Settings()
        app = FastAPI()

        @app.get("/set")
        def set_(response: Response, settings: Settings = settings) -> None:
            set_session_cookies(response, "raw", "csrf", settings)

        headers = TestClient(app).get("/set").headers.get_list("set-cookie")
        session_c, csrf_c = (h.lower() for h in headers)
        for header in (session_c, csrf_c):
            assert "samesite=lax" in header and "path=/" in header
            assert "domain=.example.com" in header
            assert ("secure" in header) == secure
            assert f"max-age={14 * 86400}" in header
        assert "httponly" in session_c
        assert "httponly" not in csrf_c


def test_me_returns_profile_with_valid_session_and_401_without(env: Env) -> None:
    user = env.user(timezone="UTC")
    client = env.app()
    assert client.get("/me").status_code == 401
    assert client.get("/me").json() == {"detail": "not_authenticated"}
    raw, csrf, _ = env.login(user)
    cookies(client, raw, csrf)
    body = client.get("/me").json()
    assert body == {"id": str(user.id), "email": "u@example.test", "timezone": "UTC"}


def test_me_401_for_garbage_revoked_expired_idle_and_disabled(env: Env) -> None:
    client = env.app()
    cookies(client, "garbage", "x")
    assert client.get("/me").status_code == 401

    user = env.user()
    raw, csrf, row = env.login(user)
    cookies(client, raw, csrf)
    assert client.get("/me").status_code == 200
    env.clock.now = T0 + timedelta(hours=73)
    assert client.get("/me").status_code == 401  # idle expired

    env.clock.now = T0
    raw, csrf, row = env.login(user)
    cookies(client, raw, csrf)
    row.idle_expires_at = T0 + timedelta(days=30)
    env.clock.now = T0 + timedelta(days=15)
    assert client.get("/me").status_code == 401  # absolute expired

    env.clock.now = T0
    raw, csrf, row = env.login(user)
    cookies(client, raw, csrf)
    sessions.revoke(env.db, row.id, T0)
    assert client.get("/me").status_code == 401  # revoked

    raw, csrf, _ = env.login(user)
    cookies(client, raw, csrf)
    user.disabled_at = T0
    env.db.flush()
    assert client.get("/me").status_code == 401  # disabled


def test_logout_revokes_server_side_and_clears_cookies(env: Env) -> None:
    raw, csrf, row = env.login(env.user())
    client = env.app()
    cookies(client, raw, csrf)
    response = client.post("/auth/logout", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 204
    cleared = [h.lower() for h in response.headers.get_list("set-cookie")]
    assert len(cleared) == 2 and all("max-age=0" in h and "path=/" in h for h in cleared)
    assert row.revoked_at is not None
    client.cookies.set("tracker_session", raw)
    assert client.get("/me").status_code == 401


def test_raw_tokens_never_stored_or_logged(env: Env, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    raw, csrf, row = env.login(env.user())
    client = env.app()
    cookies(client, raw, csrf)
    client.get("/me")
    client.post("/auth/logout", headers={"X-CSRF-Token": csrf})
    assert row.token_hash == sessions.hash_token(raw) != raw
    stored = env.db.execute(select(UserSession.token_hash, UserSession.csrf_secret)).all()
    assert all(raw not in value for pair in stored for value in pair)
    assert raw not in caplog.text and csrf not in caplog.text


def test_idle_expiry_slides_but_writes_at_most_once_per_five_minutes(env: Env) -> None:
    raw, _, row = env.login(env.user())
    settings = get_settings()
    env.clock.now = T0 + timedelta(minutes=4)
    assert sessions.resolve(env.db, raw, env.clock.now, settings) is not None
    assert row.last_seen_at == T0
    env.clock.now = T0 + timedelta(minutes=5)
    sessions.resolve(env.db, raw, env.clock.now, settings)
    assert row.last_seen_at == env.clock.now
    assert row.idle_expires_at == env.clock.now + timedelta(hours=72)
    env.clock.now += timedelta(minutes=2)
    sessions.resolve(env.db, raw, env.clock.now, settings)
    assert row.last_seen_at == T0 + timedelta(minutes=5)


@pytest.mark.parametrize("secret", ["", "short"])
@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_missing_or_short_session_secret_fails_startup_without_echoing_it(
    environment: str, secret: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ENVIRONMENT", environment)
    monkeypatch.setenv("SESSION_SECRET", secret)
    get_settings.cache_clear()
    with pytest.raises(ConfigError) as info:
        create_app()
    assert not secret or secret not in str(info.value)


def test_revoke_all_for_user_revokes_every_session(env: Env) -> None:
    user = env.user()
    rows = [env.login(user)[2] for _ in range(2)]
    sessions.revoke_all_for_user(env.db, user.id, T0)
    env.db.expire_all()
    assert all(r.revoked_at is not None for r in rows)


def test_host_prefixed_cookie_names_outside_local_without_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SESSION_SECRET", SECRET)
    for environment, domain, prefix in (
        ("prod", None, "__Host-"),
        ("prod", ".example.com", ""),
        ("local", None, ""),
    ):
        monkeypatch.setenv("ENVIRONMENT", environment)
        monkeypatch.delenv("COOKIE_DOMAIN", raising=False)
        if domain:
            monkeypatch.setenv("COOKIE_DOMAIN", domain)
        settings = Settings()
        assert settings.session_cookie == f"{prefix}tracker_session"
        assert settings.csrf_cookie == f"{prefix}tracker_csrf"


def test_purge_expired_deletes_only_sessions_dead_for_over_seven_days(env: Env) -> None:
    user = env.user()
    old = env.login(user)[2]
    old.expires_at = T0 - timedelta(days=8)
    revoked = env.login(user)[2]
    revoked.revoked_at = T0 - timedelta(days=8)
    recent = env.login(user)[2]
    recent.revoked_at = T0 - timedelta(days=1)
    live = env.login(user)[2]
    env.db.flush()
    assert sessions.purge_expired(env.db, T0) == 2
    left = set(env.db.execute(select(UserSession.id)).scalars())
    assert left == {recent.id, live.id}


def test_creating_eleventh_session_revokes_the_oldest(env: Env) -> None:
    user = env.user()
    rows = []
    for minute in range(11):
        env.clock.now = T0 + timedelta(minutes=minute)
        rows.append(env.login(user)[2])
    env.db.expire_all()
    assert rows[0].revoked_at == env.clock.now
    assert all(r.revoked_at is None for r in rows[1:])
