"""Time-budgeted sync: partial outcome, resumable initial sync, no duplicates."""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import EmailThread, SyncState
from app.providers.gmail import FakeGmailClient, ThreadSummary
from app.services import sync
from app.services.sync import SyncPartial, SyncResult, run_sync
from tests.clocks import StepClock
from tests.fixtures.gmail_threads import OWNER
from tests.test_sync import CLASSIFIER, NOW, fake, make_user, thread_ids, threads


class SpyClient(FakeGmailClient):
    """Records the page tokens the initial listing asks for."""

    tokens: list[str | None]

    def list_threads(
        self, query: str, page_token: str | None = None
    ) -> tuple[list[ThreadSummary], str | None]:
        self.tokens.append(page_token)
        return super().list_threads(query, page_token)


def spy(page_size: int) -> SpyClient:
    client = SpyClient(OWNER, threads(), now=NOW, page_size=page_size)
    client.tokens = []
    return client


def run_slice(
    session: Session, user_id: uuid.UUID, client: FakeGmailClient, budget_seconds: float
) -> SyncResult | SyncPartial:
    clock = StepClock(NOW, step=1.0)
    result = run_sync(
        session,
        user_id,
        client,
        CLASSIFIER,
        NOW,
        commit=session.flush,
        sleep=lambda _: None,
        clock=clock,
        deadline=NOW + (clock.step * budget_seconds),
    )
    assert isinstance(result, SyncResult | SyncPartial)
    return result


def state_of(session: Session, user_id: uuid.UUID) -> SyncState:
    state = session.get(SyncState, user_id, populate_existing=True)
    assert state is not None
    return state


@pytest.fixture
def user_id(db_session: Session) -> uuid.UUID:
    return make_user(db_session)


def test_deadline_stops_the_initial_sync_with_a_partial_outcome_and_a_free_lease(
    db_session: Session, user_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sync, "BATCH_SIZE", 1)
    result = run_slice(db_session, user_id, fake(page_size=2), budget_seconds=3)
    assert isinstance(result, SyncPartial) and result.mode == "initial"
    state = state_of(db_session, user_id)
    assert (state.status, state.lease_expires_at) == ("idle", None)
    assert state.initial_sync_done is False and state.history_id is None
    assert state.last_synced_at is None  # still "never synced": first in line next run
    assert state.pending_history_id is not None


def test_initial_sync_resumes_across_runs_without_duplicates_and_stores_history_id_at_the_end(
    db_session: Session, user_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sync, "BATCH_SIZE", 1)
    reference = make_user(db_session)
    sync.run_sync(db_session, reference, fake(), CLASSIFIER, NOW, commit=db_session.flush)
    client = spy(page_size=2)
    results = []
    for _ in range(20):
        results.append(run_slice(db_session, user_id, client, budget_seconds=6))
        if isinstance(results[-1], SyncResult):
            break
        assert state_of(db_session, user_id).history_id is None  # only stored on completion
    assert isinstance(results[-1], SyncResult) and len(results) >= 2
    assert thread_ids(db_session, user_id) == thread_ids(db_session, reference)
    rows = db_session.scalar(
        select(func.count()).select_from(EmailThread).where(EmailThread.user_id == user_id)
    )
    assert rows == len(thread_ids(db_session, user_id))  # no duplicates
    state = state_of(db_session, user_id)
    assert state.initial_sync_done is True and state.history_id is not None
    assert (state.pending_history_id, state.list_page_token) == (None, None)


def test_the_next_run_continues_from_the_stored_page_token_instead_of_relisting(
    db_session: Session, user_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sync, "BATCH_SIZE", 1)
    client = spy(page_size=1)  # one thread per page, so a page ends with each batch
    first = run_slice(db_session, user_id, client, budget_seconds=3)
    assert isinstance(first, SyncPartial)
    token = state_of(db_session, user_id).list_page_token
    assert token is not None  # we are past page one
    client.tokens.clear()
    run_slice(db_session, user_id, client, budget_seconds=3)
    assert client.tokens[0] == token  # resumed there, not from the first page


def test_deadline_with_no_budget_left_still_makes_progress_every_run(
    db_session: Session, user_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sync, "BATCH_SIZE", 1)
    result = run_slice(db_session, user_id, fake(page_size=2), budget_seconds=0)
    assert isinstance(result, SyncPartial) and result.threads_seen == 1  # one batch, then stop


def test_incremental_deadline_keeps_the_history_id_and_finishes_next_run(
    db_session: Session, user_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = fake()
    sync.run_sync(db_session, user_id, client, CLASSIFIER, NOW, commit=db_session.flush)
    before = state_of(db_session, user_id).history_id
    for thread in ("t-new-1", "t-new-2", "t-new-3"):
        client.add_message(
            thread,
            from_address="jobs@umbrella.example",
            subject="We received your application",
            sent_at=NOW,
        )
    monkeypatch.setattr(sync, "BATCH_SIZE", 1)
    partial = run_slice(db_session, user_id, client, budget_seconds=3)
    assert isinstance(partial, SyncPartial) and partial.mode == "incremental"
    assert state_of(db_session, user_id).history_id == before  # not advanced past unseen changes
    for _ in range(10):
        done = run_slice(db_session, user_id, client, budget_seconds=30)
        if isinstance(done, SyncResult):
            break
    assert isinstance(done, SyncResult) and done.mode == "incremental"
    assert {"t-new-1", "t-new-2", "t-new-3"} <= thread_ids(db_session, user_id)
    assert state_of(db_session, user_id).history_id != before
