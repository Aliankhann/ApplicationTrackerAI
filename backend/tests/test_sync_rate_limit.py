"""Rate limits pause the sync (progress kept, lease freed) instead of failing it; the initial window
comes from the `initial_sync_days` setting."""

import logging
import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy.orm import Session

from app.config import get_settings
from app.jobs.tick import TickSummary
from app.models import SyncState
from app.providers.gmail import FakeGmailClient, GmailRateLimited
from app.providers.gmail.pacing import TokenBucket
from app.providers.gmail.rest import RestGmailClient
from app.repositories import sync_state as repo
from app.services import sync
from app.services.sync import SyncFailed, SyncPaused, SyncResult, run_sync
from tests.fake_gmail_api import FakeGmailApi
from tests.fixtures.gmail_threads import OWNER, build_threads
from tests.test_cron import MONDAY, tick
from tests.test_gmail_pacing import FakeTime, Limiter
from tests.test_sessions import Env, env  # noqa: F401
from tests.test_sync import CLASSIFIER, DAY, NOW, RateLimitedClient, fake, make_user, thread_ids
from tests.test_sync_api import _keyring as _keyring
from tests.test_sync_api import app_for, connect, users_with_tokens


@pytest.fixture
def user_id(db_session: Session) -> uuid.UUID:
    return make_user(db_session)


def attempt(session: Session, user_id: uuid.UUID, client: FakeGmailClient):  # type: ignore[no-untyped-def]
    return run_sync(
        session, user_id, client, CLASSIFIER, NOW, commit=session.flush, sleep=lambda _: None
    )


def state_of(session: Session, user_id: uuid.UUID) -> SyncState:
    state = session.get(SyncState, user_id, populate_existing=True)
    assert state is not None
    return state


# ---------- pause instead of fail ----------


def test_a_rate_limit_that_never_lifts_pauses_the_sync_keeping_the_fetched_threads(
    db_session: Session, user_id: uuid.UUID
) -> None:
    client = fake()
    client.rate_limit_threads(["t-reject"])  # refused on every attempt
    result = attempt(db_session, user_id, client)
    assert isinstance(result, SyncPaused) and result.mode == "initial"
    state = state_of(db_session, user_id)
    assert (state.status, state.last_error) == ("paused", "rate_limited")
    assert state.lease_expires_at is None and state.consecutive_rate_limits == 1
    assert state.pending_history_id is not None and state.initial_sync_done is False
    assert {"t-confirm", "t-interview"} <= thread_ids(db_session, user_id)  # progress kept
    assert "t-reject" not in thread_ids(db_session, user_id)


def test_the_next_run_continues_from_a_paused_sync_and_a_success_resets_the_counter(
    db_session: Session, user_id: uuid.UUID
) -> None:
    client = fake()
    client.rate_limit_threads(["t-reject"])
    assert isinstance(attempt(db_session, user_id, client), SyncPaused)
    client.clear_rate_limits()
    client.fetched_thread_ids.clear()
    result = attempt(db_session, user_id, client)
    assert isinstance(result, SyncResult)
    assert "t-reject" in thread_ids(db_session, user_id)
    state = state_of(db_session, user_id)
    assert (state.status, state.last_error, state.consecutive_rate_limits) == ("idle", None, 0)
    assert state.initial_sync_done is True


def test_a_single_request_rate_limit_is_retried_then_pauses_with_the_backoff_sequence(
    db_session: Session, user_id: uuid.UUID
) -> None:
    sleeps: list[float] = []
    result = run_sync(
        db_session,
        user_id,
        RateLimitedClient(99),
        CLASSIFIER,
        NOW,
        commit=db_session.flush,
        sleep=sleeps.append,
    )
    assert isinstance(result, SyncPaused)
    assert sleeps == [1.0, 2.0, 4.0, 8.0]
    assert state_of(db_session, user_id).status == "paused"


def test_three_consecutive_rate_limited_runs_record_an_error(
    db_session: Session, user_id: uuid.UUID
) -> None:
    for expected in (1, 2):
        assert isinstance(attempt(db_session, user_id, RateLimitedClient(99)), SyncPaused)
        assert state_of(db_session, user_id).consecutive_rate_limits == expected
    with pytest.raises(SyncFailed):
        attempt(db_session, user_id, RateLimitedClient(99))
    state = state_of(db_session, user_id)
    assert (state.status, state.last_error, state.lease_expires_at) == (
        "error",
        "rate_limited",
        None,
    )
    assert state.consecutive_rate_limits == 0  # reset, so a later throttle pauses again


def test_a_successful_run_between_rate_limited_runs_resets_the_count(
    db_session: Session, user_id: uuid.UUID
) -> None:
    for _ in range(2):
        attempt(db_session, user_id, RateLimitedClient(99))
    assert isinstance(attempt(db_session, user_id, fake()), SyncResult)
    assert state_of(db_session, user_id).consecutive_rate_limits == 0


def test_rate_limit_hits_are_counted_in_the_run_log(
    db_session: Session, user_id: uuid.UUID, caplog: pytest.LogCaptureFixture
) -> None:
    client = fake()
    client.rate_limit_threads(["t-reject"], times=1)
    with caplog.at_level(logging.INFO, logger="app.sync"):
        assert isinstance(attempt(db_session, user_id, client), SyncPaused)
    paused = [r for r in caplog.records if r.getMessage() == "sync.paused"]
    assert paused and paused[0].rate_limit_hits == 1  # type: ignore[attr-defined]


def test_the_fake_batch_raises_with_the_threads_it_did_fetch() -> None:
    client = fake()
    client.rate_limit_threads(["t-reject"])
    with pytest.raises(GmailRateLimited) as raised:
        client.get_threads(["t-confirm", "t-reject"])
    assert [t.thread_id for t in raised.value.fetched] == ["t-confirm"]


# ---------- API and tick ----------


def test_manual_sync_now_returns_paused_with_the_reason_and_status_shows_it(
    env: Env,  # noqa: F811
) -> None:
    user = env.user()
    connect(env, user)

    def limited(session: Session, user_id: uuid.UUID) -> FakeGmailClient:
        client = fake()
        client.rate_limit_threads(["t-reject"])
        return client

    client = app_for(env, user, limited)
    assert client.post("/sync").json() == {"status": "paused", "reason": "rate_limited"}
    status = client.get("/sync").json()
    assert (status["status"], status["last_error"]) == ("paused", "rate_limited")
    assert client.post("/sync").status_code == 200  # Sync now stays available


def test_tick_counts_paused_users_and_continues_them_on_the_next_run_despite_the_min_gap(
    env: Env,  # noqa: F811
) -> None:
    limited_user, other = users_with_tokens(env, 2)
    env.clock.now = MONDAY

    def factory(session: Session, user_id: uuid.UUID) -> FakeGmailClient:
        client = fake()
        if user_id == limited_user.id:
            client.rate_limit_threads(["t-reject"])
        return client

    summary = tick(env, factory=factory)
    assert (summary.sync_paused, summary.sync_completed, summary.sync_failed) == (1, 1, 0)
    assert "sync_paused" in TickSummary.__dataclass_fields__
    state = env.db.get(SyncState, limited_user.id, populate_existing=True)
    assert state is not None and state.status == "paused"
    env.db.get(SyncState, other.id).last_synced_at = MONDAY  # type: ignore[union-attr]
    state.last_synced_at = MONDAY  # recent: only "paused" keeps this user due
    env.db.commit()
    env.clock.now = MONDAY + timedelta(hours=1)
    summary = tick(env)
    assert (summary.sync_completed, summary.sync_paused) == (1, 0)
    assert "t-reject" in thread_ids(env.db, limited_user.id)


# ---------- initial window setting ----------


def two_aged_threads() -> FakeGmailClient:
    built = {
        tid: [m.__class__(**{**m.__dict__, "sent_at": NOW - age * DAY}) for m in msgs]
        for tid, age, msgs in (
            ("t-new", 20, fake()._threads["t-confirm"]),
            ("t-old", 40, fake()._threads["t-confirm"]),
        )
    }
    for tid, msgs in built.items():
        built[tid] = [m.__class__(**{**m.__dict__, "thread_id": tid}) for m in msgs]
    return FakeGmailClient(OWNER, built, now=NOW)


def test_the_default_initial_window_is_30_days(db_session: Session, user_id: uuid.UUID) -> None:
    assert get_settings().initial_sync_days == 30
    assert isinstance(attempt(db_session, user_id, two_aged_threads()), SyncResult)
    assert thread_ids(db_session, user_id) == {"t-new"}


def test_the_initial_window_comes_from_the_setting(
    db_session: Session, user_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INITIAL_SYNC_DAYS", "60")
    get_settings.cache_clear()
    assert isinstance(attempt(db_session, user_id, two_aged_threads()), SyncResult)
    assert thread_ids(db_session, user_id) == {"t-new", "t-old"}


@pytest.mark.parametrize("value", ["0", "366"])
def test_the_initial_window_setting_is_validated(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("INITIAL_SYNC_DAYS", value)
    get_settings.cache_clear()
    with pytest.raises(ValueError):
        get_settings()


# ---------- follow-up fixes: deadline, page offset, fairness ----------


def test_a_rest_client_that_is_always_rate_limited_finishes_within_the_manual_budget(
    user_id: uuid.UUID, db_session: Session
) -> None:
    api = FakeGmailApi.from_metas(OWNER, build_threads(NOW))
    api.page_size = 100
    time_ = FakeTime()
    limiter = Limiter(api, dict.fromkeys(api.threads, 999), retry_after="20")
    http = httpx.Client(transport=httpx.MockTransport(limiter))
    client = RestGmailClient(
        lambda _: api.valid_token,
        http,
        bucket=TokenBucket(100.0, time_.clock, time_.sleep),
        sleep=time_.sleep,
    )
    result = run_sync(
        db_session,
        user_id,
        client,
        CLASSIFIER,
        NOW,
        commit=db_session.flush,
        sleep=time_.sleep,
        clock=lambda: NOW + timedelta(seconds=time_.now),
        deadline=NOW + timedelta(seconds=25),
        ensure_progress=False,
    )
    assert isinstance(result, SyncPaused)
    assert time_.now <= 25.0  # the 20 s Retry-After fits once; a second one would not


def test_a_resumed_page_requests_only_the_ids_not_yet_fetched(
    db_session: Session, user_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sync, "BATCH_SIZE", 2)
    client = fake()
    client.rate_limit_threads(["t-reject"])
    assert isinstance(attempt(db_session, user_id, client), SyncPaused)
    assert state_of(db_session, user_id).list_page_offset == 3  # sent, interview, confirm done
    client.clear_rate_limits()
    client.fetched_thread_ids.clear()
    assert isinstance(attempt(db_session, user_id, client), SyncResult)
    assert client.fetched_thread_ids == ["t-reject", "t-newsletter"]
    state = state_of(db_session, user_id)
    assert (state.list_page_offset, state.list_page_token) == (0, None)


def test_the_offset_resets_when_moving_to_the_next_page(
    db_session: Session, user_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sync, "BATCH_SIZE", 2)
    client = fake(page_size=2)
    client.rate_limit_threads(["t-reject"])  # on the second page
    assert isinstance(attempt(db_session, user_id, client), SyncPaused)
    state = state_of(db_session, user_id)
    assert state.list_page_token is not None and state.list_page_offset == 1


def test_due_users_are_never_synced_then_oldest_then_paused_last(env: Env) -> None:  # noqa: F811
    never, old, recent_enough, paused = users_with_tokens(env, 4)
    env.clock.now = MONDAY
    env.db.add_all(
        [
            SyncState(user_id=old.id, last_synced_at=MONDAY - timedelta(hours=40)),
            SyncState(user_id=recent_enough.id, last_synced_at=MONDAY - timedelta(hours=20)),
            SyncState(
                user_id=paused.id, last_synced_at=MONDAY - timedelta(hours=90), status="paused"
            ),
        ]
    )
    env.db.commit()
    due = repo.due_for_sync(env.db, MONDAY, timedelta(hours=12))
    assert due == [never.id, old.id, recent_enough.id, paused.id]
