"""The daily cron tick: auth, parts, time budget, once-a-day maintenance, sync selection."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import (
    CRON_ROUTES,
    get_classifier,
    get_client_factory,
    get_clock,
    get_email_sender,
)
from app.config import get_settings
from app.jobs import maintenance
from app.jobs.tick import TickSummary, run_tick
from app.models import JobRun, SyncState, User
from app.providers.email import FakeEmailSender
from app.providers.gmail import FakeGmailClient
from app.security import ratelimit
from tests import test_scheduler as sched
from tests.clocks import StepClock
from tests.test_digest import new_user, seed
from tests.test_sessions import Env, env  # noqa: F401
from tests.test_sync import CLASSIFIER, fake, thread_ids
from tests.test_sync_api import BOTH, connect, users_with_tokens
from tests.test_sync_api import _keyring as _keyring

CRON_SECRET = "c" * 40
AUTH = {"Authorization": f"Bearer {CRON_SECRET}"}
MONDAY = datetime(2026, 3, 9, 12, 0, tzinfo=UTC)  # 08:00 Toronto (EDT): before any 9-11 window
SUMMARY_KEYS = set(TickSummary.__dataclass_fields__)


def tick_client(
    env: Env,  # noqa: F811
    clock: Callable[[], datetime] | None = None,
    factory: Callable[[Session, uuid.UUID], FakeGmailClient] = lambda s, u: fake(),
    sender: FakeEmailSender | None = None,
) -> TestClient:
    client = env.app()
    overrides = client.app.dependency_overrides  # type: ignore[attr-defined]
    overrides[get_clock] = lambda: clock or env.clock
    overrides[get_client_factory] = lambda: factory
    overrides[get_classifier] = lambda: CLASSIFIER
    overrides[get_email_sender] = lambda: sender or FakeEmailSender()
    return client


def tick(env: Env, **kwargs: object) -> TickSummary:  # noqa: F811
    """run_tick directly, with the real settings and a fake clock."""
    env.app()
    clock = kwargs.pop("clock", None) or env.clock
    factory = kwargs.pop("factory", lambda s, u: fake())
    return run_tick(
        env.db,
        get_settings(),
        clock,  # type: ignore[arg-type]
        factory,  # type: ignore[arg-type]
        CLASSIFIER,
        FakeEmailSender(),
    )


# ---------- auth ----------


def test_cron_tick_is_401_without_or_with_a_wrong_secret(env: Env) -> None:  # noqa: F811
    client = tick_client(env)
    for headers in (
        {},
        {"Authorization": "Bearer wrong"},
        {"Authorization": f"Bearer {CRON_SECRET}x"},
        {"Authorization": CRON_SECRET},  # no scheme
        {"Authorization": f"Basic {CRON_SECRET}"},
    ):
        response = client.get("/internal/cron/tick", headers=headers)
        assert (response.status_code, response.json()) == (401, {"detail": "unauthorized"})


def test_cron_tick_fails_closed_when_no_secret_is_configured_locally(
    env: Env,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CRON_SECRET", "")
    client = tick_client(env)
    assert (
        client.get("/internal/cron/tick", headers={"Authorization": "Bearer "}).status_code == 401
    )
    assert client.get("/internal/cron/tick").status_code == 401


def test_cron_tick_needs_no_session_or_csrf_and_returns_counts_only(env: Env) -> None:  # noqa: F811
    client = tick_client(env)
    response = client.get("/internal/cron/tick", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == SUMMARY_KEYS
    assert all(isinstance(v, int | bool) for v in body.values())


def test_cron_tick_is_get_only_and_hidden_from_the_api_schema(env: Env) -> None:  # noqa: F811
    client = tick_client(env)
    assert {method for method, _ in CRON_ROUTES} == {"GET"}
    assert client.post("/internal/cron/tick", headers=AUTH).status_code in {401, 403, 405}
    assert "/internal" not in client.get("/openapi.json").text


# ---------- parts ----------


def test_cron_tick_runs_sync_followups_digest_and_maintenance_in_one_pass(
    env: Env,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FOLLOWUP_WINDOW_MODE", "daily")
    monkeypatch.delenv("DIGEST_SEND_AFTER_LOCAL_HOUR")
    env.app()
    syncer = env.user()
    connect(env, syncer)
    follower, fclient, _, _ = sched.setup(env.db)
    connect(env, follower, BOTH)
    digester = new_user(env.db, "America/Toronto")
    seed(env, digester, now=MONDAY)
    env.db.commit()
    env.clock.now = MONDAY
    sender = FakeEmailSender()
    summary = run_tick(
        env.db,
        get_settings(),
        env.clock,
        lambda s, u: fclient if u == follower.id else fake(),
        CLASSIFIER,
        sender,
    )
    assert summary.sync_completed == 2  # both token holders
    assert summary.followups_drafted == 1 and fclient.drafts
    assert summary.digest_sent >= 1 and any(m.to_address == digester.email for m in sender.sent)
    assert summary.maintenance_ran == 1
    assert summary.budget_exhausted is False
    assert thread_ids(env.db, syncer.id)


def test_cron_tick_maintenance_runs_once_per_utc_day(env: Env) -> None:  # noqa: F811
    env.clock.now = datetime(2026, 3, 9, 0, 5, tzinfo=UTC)
    assert tick(env).maintenance_ran == 1
    env.clock.now = datetime(2026, 3, 9, 23, 55, tzinfo=UTC)
    assert tick(env).maintenance_ran == 0
    env.clock.now = datetime(2026, 3, 10, 0, 1, tzinfo=UTC)
    assert tick(env).maintenance_ran == 1
    row = env.db.get(JobRun, "maintenance")
    assert row is not None and row.last_run_at == env.clock.now


def test_a_failed_purge_does_not_consume_the_days_maintenance_run(
    env: Env,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env.clock.now = MONDAY
    env.db.commit()

    def boom(*_: object) -> None:
        raise RuntimeError("synthetic")

    monkeypatch.setattr(ratelimit, "purge_old", boom)
    with pytest.raises(RuntimeError):
        maintenance.run_daily(env.db, MONDAY)
    env.db.rollback()  # the request session is closed (rolled back) when the route fails
    monkeypatch.undo()
    assert maintenance.run_daily(env.db, MONDAY) is True


# ---------- sync selection ----------


def test_cron_sync_picks_only_users_past_the_min_gap_oldest_first(env: Env) -> None:  # noqa: F811
    never, old, older, recent = users_with_tokens(env, 4)
    env.clock.now = MONDAY
    for user, age in ((old, 20), (older, 30), (recent, 2)):  # hours since last sync
        env.db.add(SyncState(user_id=user.id, last_synced_at=MONDAY - timedelta(hours=age)))
    env.db.commit()
    order: list[uuid.UUID] = []

    def factory(session: Session, user_id: uuid.UUID) -> FakeGmailClient:
        order.append(user_id)
        return fake()

    summary = tick(env, factory=factory)
    assert order == [never.id, older.id, old.id]  # never-synced first, then oldest; recent skipped
    assert summary.sync_completed == 3


# ---------- time budget ----------


def test_cron_tick_stops_cleanly_when_the_budget_runs_out_and_next_tick_continues(
    env: Env,  # noqa: F811
) -> None:
    users = users_with_tokens(env, 5)
    env.db.commit()
    # Every clock read costs 40 s: the sync share (60% of 220 s) allows only the first user(s).
    slow = StepClock(MONDAY, step=40.0)
    first = tick(env, clock=slow)
    done = first.sync_completed + first.sync_partial
    assert 1 <= done < len(users)
    assert first.budget_exhausted is True
    assert first.maintenance_ran == 1  # the cheap parts after it still ran
    synced = {u.id for u in users if thread_ids(env.db, u.id)}
    assert len(synced) == done  # nothing half-written for users it never reached
    env.clock.now = MONDAY + timedelta(minutes=1)
    for _ in range(len(users)):  # the unreached users are next in line
        if tick(env).sync_completed == 0:
            break
    assert {u.id for u in users if thread_ids(env.db, u.id)} == {u.id for u in users}


def test_cron_tick_with_time_to_spare_is_not_exhausted(env: Env) -> None:  # noqa: F811
    users_with_tokens(env, 2)
    summary = tick(env, clock=StepClock(MONDAY, step=0.01))
    assert summary.sync_completed == 2 and summary.budget_exhausted is False


def test_cron_tick_logs_counts_and_the_flag_only(
    env: Env,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    (user,) = users_with_tokens(env, 1)
    with caplog.at_level(logging.INFO):
        tick(env)
    (record,) = [r for r in caplog.records if r.getMessage() == "cron.tick"]
    extras = {k for k in record.__dict__ if k in SUMMARY_KEYS}
    assert extras == SUMMARY_KEYS
    assert str(user.id) not in repr(record.__dict__)


def test_digest_goes_out_at_tick_time_in_daily_mode_once_per_local_date(
    env: Env,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DIGEST_SEND_AFTER_LOCAL_HOUR")
    user = new_user(env.db, "America/Toronto")
    seed(env, user, now=MONDAY)
    env.db.commit()
    env.clock.now = MONDAY  # 08:00 local would be too early only with a send-after hour set
    first = tick(env)
    env.clock.now = MONDAY + timedelta(minutes=30)
    assert first.digest_sent == 1 and tick(env).digest_sent == 0
    assert env.db.scalars(select(User).where(User.id == user.id)).one()


def test_digest_send_after_local_hour_still_defers_when_configured(env: Env) -> None:  # noqa: F811
    user = new_user(env.db, "America/Toronto")
    seed(env, user, now=MONDAY)
    env.db.commit()
    env.clock.now = MONDAY - timedelta(hours=2)  # 06:00 local, hour is 8 (conftest)
    assert tick(env).digest_sent == 0
