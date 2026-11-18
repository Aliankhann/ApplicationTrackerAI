"""US-34 manual sync and status, the job entry points, and the follow-up compose gate."""

import base64
import json
import logging
import os
import uuid
from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_sync_launcher
from app.jobs import scheduler as scheduler_job
from app.jobs import sync as sync_job
from app.log import AllowlistJsonFormatter
from app.models import EmailThread, OAuthToken, SyncState, TokenStatus, User
from app.providers.gmail import DraftRef, DraftRequest, FakeGmailClient, GmailAuthRevoked
from app.providers.gmail.draft_message import build_raw_message
from app.providers.google.scopes import GMAIL_COMPOSE, GMAIL_READONLY
from app.providers.google.tokens import ACCESS_TOKENS
from app.repositories import oauth_tokens
from app.security.crypto import get_keyring
from app.services import gmail_access
from app.services.sync_runner import SyncOutcome, run_user_sync
from tests import test_scheduler as sched
from tests.fake_gmail_api import REFRESH_TOKEN, FakeGmailApi
from tests.fixtures.gmail_threads import OWNER, build_threads
from tests.test_applications_api import login
from tests.test_sessions import T0, Env, env  # noqa: F401
from tests.test_signin import GOOGLE_ENV
from tests.test_sync import CLASSIFIER, fake, thread_ids

READONLY = GMAIL_READONLY
BOTH = f"{GMAIL_READONLY} {GMAIL_COMPOSE}"


@pytest.fixture(autouse=True)
def _keyring(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEYS", f"1:{key}")
    monkeypatch.setenv("TOKEN_ENCRYPTION_CURRENT_VERSION", "1")
    ACCESS_TOKENS.clear()
    yield
    ACCESS_TOKENS.clear()


def connect(env: Env, user: User, scopes: str = READONLY) -> None:  # noqa: F811
    oauth_tokens.save_refresh_token(env.db, user.id, REFRESH_TOKEN, scopes, get_keyring())
    env.db.flush()


class Launches:
    """A background-task stand-in: records launches, optionally running a fake-client sync."""

    def __init__(
        self,
        env: Env,  # noqa: F811
        run: bool = False,
        factory: Callable[[Session, uuid.UUID], FakeGmailClient] = lambda s, u: fake(),
    ) -> None:
        self.env, self.run, self.factory = env, run, factory
        self.calls: list[uuid.UUID] = []

    def __call__(self, user_id: uuid.UUID) -> None:
        self.calls.append(user_id)
        if self.run:
            run_user_sync(
                self.env.db,
                user_id,
                self.env.clock.now,
                self.factory,
                CLASSIFIER,
                sleep=lambda _: None,
            )


def app_for(env: Env, user: User, launches: Launches) -> TestClient:  # noqa: F811
    client = login(env, user)
    client.app.dependency_overrides[get_sync_launcher] = lambda: launches  # type: ignore[attr-defined]
    return client


# ---------- POST /sync, GET /sync ----------


def test_us34_sync_without_a_live_token_is_409_gmail_not_connected(env: Env) -> None:  # noqa: F811
    user = env.user()
    launches = Launches(env)
    client = app_for(env, user, launches)
    response = client.post("/sync")
    assert (response.status_code, response.json()) == (409, {"detail": "gmail_not_connected"})
    connect(env, user)
    oauth_tokens.mark_revoked(env.db, user.id)
    assert client.post("/sync").status_code == 409
    assert launches.calls == []


def test_us34_sync_starts_in_the_background_and_status_reports_the_result(env: Env) -> None:  # noqa: F811
    user = env.user()
    connect(env, user)
    launches = Launches(env, run=True)
    client = app_for(env, user, launches)
    assert client.get("/sync").json() == {
        "status": "idle",
        "last_synced_at": None,
        "initial_sync_done": False,
        "last_error": None,
    }
    response = client.post("/sync")
    assert (response.status_code, response.json()) == (202, {"status": "started"})
    assert launches.calls == [user.id]
    status = client.get("/sync").json()
    assert status["status"] == "idle" and status["initial_sync_done"] is True
    assert (
        status["last_synced_at"].startswith("2026-01-01T12:00:00") and status["last_error"] is None
    )
    assert {"t-confirm", "t-interview", "t-reject"} <= thread_ids(env.db, user.id)


def test_us34_second_request_while_running_returns_the_existing_run_not_a_new_one(env: Env) -> None:  # noqa: F811
    user = env.user()
    connect(env, user)
    env.db.add(
        SyncState(user_id=user.id, status="running", lease_expires_at=T0 + timedelta(minutes=5))
    )
    env.db.flush()
    launches = Launches(env)
    client = app_for(env, user, launches)
    response = client.post("/sync")
    assert (response.status_code, response.json()) == (200, {"status": "already_running"})
    assert launches.calls == []
    assert client.get("/sync").json()["status"] == "running"


def test_us34_an_expired_lease_is_a_crashed_sync_so_a_new_one_starts(env: Env) -> None:  # noqa: F811
    user = env.user()
    connect(env, user)
    env.db.add(
        SyncState(user_id=user.id, status="running", lease_expires_at=T0 - timedelta(minutes=1))
    )
    env.db.flush()
    launches = Launches(env)
    client = app_for(env, user, launches)
    assert client.get("/sync").json()["status"] == "idle"
    assert client.post("/sync").status_code == 202 and launches.calls == [user.id]


def test_us34_sync_is_rate_limited_per_user(env: Env) -> None:  # noqa: F811
    user, other = env.user(), env.user()
    connect(env, user)
    connect(env, other)
    client = app_for(env, user, Launches(env))
    assert [client.post("/sync").status_code for _ in range(6)] == [202] * 6
    blocked = client.post("/sync")
    assert blocked.status_code == 429 and blocked.json() == {"detail": "rate_limited"}
    assert int(blocked.headers["Retry-After"]) > 0
    assert app_for(env, other, Launches(env)).post("/sync").status_code == 202  # per user


def test_us34_status_shows_stable_error_codes_and_revocation(env: Env) -> None:  # noqa: F811
    user = env.user()
    connect(env, user)
    client = app_for(env, user, Launches(env, run=True, factory=lambda s, u: _revoked_client()))
    assert client.post("/sync").status_code == 202
    assert client.get("/sync").json()["status"] == "revoked"
    assert client.get("/sync").json()["last_error"] == "auth_revoked"
    assert client.post("/sync").status_code == 409  # token flagged revoked: connect again


def _revoked_client() -> FakeGmailClient:
    client = FakeGmailClient(OWNER, build_threads(T0), now=T0)
    client.revoke()
    return client


def test_us34_status_for_a_user_without_gmail_state_is_idle_and_empty(env: Env) -> None:  # noqa: F811
    client = app_for(env, env.user(), Launches(env))
    assert client.get("/sync").json()["status"] == "idle"
    assert client.get("/gmail/status").json() == {"connected": False, "followups_enabled": False}


# ---------- job entry points ----------


def users_with_tokens(env: Env, n: int, scopes: str = READONLY) -> list[User]:  # noqa: F811
    users = [env.user() for _ in range(n)]
    for user in users:
        connect(env, user, scopes)
    return users


def test_us34_sync_job_isolates_per_user_failures_and_respects_leases(env: Env) -> None:  # noqa: F811
    ok1, boom, leased, revoked, ok2 = users_with_tokens(env, 5)
    env.db.add(
        SyncState(user_id=leased.id, status="running", lease_expires_at=T0 + timedelta(minutes=5))
    )
    env.db.flush()

    def factory(session: Session, user_id: uuid.UUID) -> Any:
        if user_id == boom.id:
            raise RuntimeError("synthetic failure")
        if user_id == revoked.id:
            raise GmailAuthRevoked
        return fake()

    outcomes = sync_job.run(
        env.db, T0, factory, CLASSIFIER, only={u.id for u in (ok1, boom, leased, revoked, ok2)}
    )
    assert outcomes == {
        SyncOutcome.COMPLETED: 2,
        SyncOutcome.ALREADY_RUNNING: 1,
        SyncOutcome.FAILED: 1,
        SyncOutcome.REVOKED: 1,
    }
    assert thread_ids(env.db, ok1.id) and thread_ids(env.db, ok2.id)  # the others still synced
    assert not thread_ids(env.db, boom.id) and not thread_ids(env.db, leased.id)
    token = env.db.get(OAuthToken, revoked.id, populate_existing=True)
    assert token is not None and token.status == TokenStatus.REVOKED


def test_us34_sync_job_visits_only_enabled_users_with_live_tokens(env: Env) -> None:  # noqa: F811
    live, revoked, disabled, never = (env.user(), env.user(), env.user(disabled_at=T0), env.user())
    for user in (live, revoked, disabled):
        connect(env, user)
    oauth_tokens.mark_revoked(env.db, revoked.id)
    seen: list[uuid.UUID] = []

    def factory(session: Session, user_id: uuid.UUID) -> FakeGmailClient:
        seen.append(user_id)
        return fake()

    sync_job.run(env.db, T0, factory, CLASSIFIER, only={live.id, revoked.id, disabled.id})
    assert seen == [live.id] and never.id not in seen


def test_us34_sync_job_runs_with_real_clock_and_logs_counts_only(
    env: Env,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    (user,) = users_with_tokens(env, 1)
    monkeypatch.setattr(sync_job, "SessionLocal", lambda: _Borrowed(env.db))
    monkeypatch.setattr(sync_job, "gmail_client_for", lambda s, u: fake())
    with caplog.at_level(logging.INFO):
        assert sync_job.main() == 0
    assert thread_ids(env.db, user.id)
    finished = [r for r in caplog.records if r.getMessage() == "sync.job_finished"]
    assert [(r.count, r.skipped, r.failed) for r in finished] == [(1, 0, 0)]  # type: ignore[attr-defined]


class _Borrowed:
    """A context manager that lends the test session without closing it."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def __enter__(self) -> Session:
        return self.session

    def __exit__(self, *exc: object) -> None:
        return None


# ---------- follow-ups need gmail.compose ----------


def test_us65_run_due_never_drafts_for_a_token_without_compose(db_session: Session) -> None:
    user, client, app, _ = sched.setup(db_session)
    oauth_tokens.save_refresh_token(db_session, user.id, REFRESH_TOKEN, READONLY, get_keyring())
    result = sched.run(db_session, user, client, sched.DAY7)
    assert result.no_compose and result.drafted == 0 and client.drafts == ()
    assert [t.state for t in sched.tasks(db_session, user, app)] == ["pending", "pending"]
    oauth_tokens.save_refresh_token(db_session, user.id, REFRESH_TOKEN, BOTH, get_keyring())
    allowed = sched.run(db_session, user, client, sched.DAY7)
    assert allowed.drafted == 1 and len(client.drafts) == 1


def test_us65_scheduler_job_visits_only_compose_users_and_isolates_failures(
    db_session: Session,
) -> None:
    with_compose, readonly_only, broken = (sched.setup(db_session) for _ in range(3))
    for (user, *_), scopes in ((with_compose, BOTH), (readonly_only, READONLY), (broken, BOTH)):
        oauth_tokens.save_refresh_token(db_session, user.id, REFRESH_TOKEN, scopes, get_keyring())
    clients = {with_compose[0].id: with_compose[1], readonly_only[0].id: readonly_only[1]}
    asked: list[uuid.UUID] = []

    def factory(session: Session, user_id: uuid.UUID) -> FakeGmailClient:
        asked.append(user_id)
        if user_id == broken[0].id:
            raise RuntimeError("synthetic failure")
        return clients[user_id]

    counts = scheduler_job.run(
        db_session,
        sched.DAY7,
        factory,
        only={u[0].id for u in (with_compose, readonly_only, broken)},
    )
    assert dict(counts) == {"skipped": 1, "drafted": 1, "users": 1, "failed": 1}
    assert readonly_only[0].id not in asked
    assert len(with_compose[1].drafts) == 1 and readonly_only[1].drafts == ()
    assert broken[1].drafts == ()


# ---------- production wiring and logs ----------


def test_us31_gmail_client_for_decrypts_the_token_and_syncs_over_the_rest_api(
    env: Env,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env.app(**GOOGLE_ENV)
    user = env.user()
    connect(env, user)
    api = FakeGmailApi.from_metas(OWNER, build_threads(T0))
    monkeypatch.setattr(
        gmail_access, "shared_http", lambda: httpx.Client(transport=api.transport())
    )
    outcome = run_user_sync(env.db, user.id, T0, gmail_access.gmail_client_for, CLASSIFIER)
    assert outcome is SyncOutcome.COMPLETED
    assert {"t-confirm", "t-interview", "t-reject"} <= thread_ids(env.db, user.id)
    assert api.refresh_count == 1  # one access token reused for every request of the sync
    with pytest.raises(GmailAuthRevoked):
        gmail_access.gmail_client_for(env.db, env.user().id)  # no token row


def test_us34_a_sync_logs_no_tokens_emails_subjects_or_snippets(
    env: Env,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    env.app(**GOOGLE_ENV)
    user = env.user()
    connect(env, user)
    api = FakeGmailApi.from_metas(OWNER, build_threads(T0))
    monkeypatch.setattr(
        gmail_access, "shared_http", lambda: httpx.Client(transport=api.transport())
    )
    httpx_logger = logging.getLogger("httpx")
    previous = httpx_logger.level
    httpx_logger.setLevel(logging.INFO)  # as configure_logging leaves it: WARNING; worst case here
    try:
        with caplog.at_level(logging.DEBUG):
            run_user_sync(env.db, user.id, T0, gmail_access.gmail_client_for, CLASSIFIER)
    finally:
        httpx_logger.setLevel(previous)
    formatter = AllowlistJsonFormatter()
    emitted = "\n".join(
        formatter.format(r) + r.getMessage() + json.dumps(r.__dict__, default=str)
        for r in caplog.records
        if not r.name.startswith("sqlalchemy")
    )
    assert "sync.completed" in emitted
    secrets = [REFRESH_TOKEN, "at-1", "Bearer", user.email, OWNER, "jobs@acme-robotics.example"]
    secrets += ["We received your application", "Synthetic snippet", "Interview invitation"]
    for secret in secrets:
        assert secret not in emitted, secret
    assert env.db.scalars(select(EmailThread)).first() is not None


def test_us65_an_invalid_recipient_releases_the_claim_instead_of_sticking_in_drafting(
    db_session: Session,
) -> None:
    user, client, app, _ = sched.setup(db_session)
    client.get_reply_recipient = lambda thread_id: "a@b.com, c@d.com"  # type: ignore[method-assign]
    real_create = client.create_draft

    def create(request: DraftRequest) -> DraftRef:
        build_raw_message(request)  # what RestGmailClient does before calling Google
        return real_create(request)

    client.create_draft = create  # type: ignore[method-assign]
    result = sched.run(db_session, user, client, sched.DAY7)
    first = sched.tasks(db_session, user, app)[0]
    assert result.drafted == 0 and client.drafts == ()
    assert (first.state, first.claimed_at, first.attempt_failures) == ("pending", None, 1)
