import uuid
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    Application,
    Classification,
    EmailThread,
    OAuthToken,
    StatusEvent,
    SyncState,
    TokenStatus,
    User,
)
from app.providers.classifier.rules import RulesProvider
from app.providers.classifier.types import ClassificationInput, ClassificationResult
from app.providers.gmail import (
    FakeGmailClient,
    GmailError,
    GmailHistoryExpired,
    GmailNotFound,
    GmailRateLimited,
    MessageMeta,
    ThreadMeta,
)
from app.services import sync
from app.services.classification import ApplicationStatus
from app.services.sync import SyncAlreadyRunning, SyncFailed, SyncResult, SyncRevoked, run_sync
from tests.fixtures.gmail_threads import OWNER, build_threads

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
DAY = timedelta(days=1)
CLASSIFIER = RulesProvider(threshold=0.5)


def make_user(session: Session) -> uuid.UUID:
    user = User(google_sub=uuid.uuid4().hex, email="u@example.test")
    session.add(user)
    session.flush()
    return user.id


SNIPPETS = {
    "t-interview": "We would like to schedule an interview",
    "t-reject": "Unfortunately we will not be moving forward with your application",
}


def threads() -> dict[str, list[MessageMeta]]:
    """Fixture threads with decisive snippets and the newsletter inside the 30-day window."""
    built = build_threads(NOW)
    for thread_id, snippet in SNIPPETS.items():
        built[thread_id][-1] = replace(built[thread_id][-1], snippet=snippet)
    built["t-newsletter"] = [
        replace(
            built["t-newsletter"][0],
            sent_at=NOW - 30 * DAY,
            subject="Weekly deals digest",
            snippet="Save big this week",
        )
    ]
    return built


def fake(page_size: int = 100) -> FakeGmailClient:
    return FakeGmailClient(OWNER, threads(), now=NOW, page_size=page_size)


def sync_once(
    session: Session, user_id: uuid.UUID, client: FakeGmailClient, **kwargs: object
) -> SyncResult:
    result = run_sync(session, user_id, client, CLASSIFIER, NOW, commit=session.flush, **kwargs)  # type: ignore[arg-type]
    assert isinstance(result, SyncResult)
    return result


def count(session: Session, model: type, user_id: uuid.UUID | None = None) -> int:
    stmt = select(func.count()).select_from(model)
    if user_id is not None and hasattr(model, "user_id"):
        stmt = stmt.where(model.user_id == user_id)
    return session.scalar(stmt) or 0


def statuses(session: Session, user_id: uuid.UUID) -> dict[str, ApplicationStatus]:
    rows = session.execute(
        select(EmailThread.gmail_thread_id, Application.status)
        .join(Application, Application.source_thread_id == EmailThread.id)
        .where(Application.user_id == user_id)
    )
    return {tid: status for tid, status in rows}


def thread_ids(session: Session, user_id: uuid.UUID) -> set[str]:
    return set(
        session.scalars(select(EmailThread.gmail_thread_id).where(EmailThread.user_id == user_id))
    )


@pytest.fixture
def user_id(db_session: Session) -> uuid.UUID:
    return make_user(db_session)


def test_initial_sync_stores_only_job_threads_and_saves_history_id(
    db_session: Session, user_id: uuid.UUID
) -> None:
    client = fake()
    profile_history = client.get_profile().history_id
    result = sync_once(db_session, user_id, client)
    ids = thread_ids(db_session, user_id)
    assert "t-newsletter" not in ids
    assert {"t-confirm", "t-interview", "t-reject", "t-sent"} == ids
    found = statuses(db_session, user_id)
    assert found["t-confirm"] == ApplicationStatus.APPLIED
    assert found["t-interview"] == ApplicationStatus.INTERVIEW
    assert found["t-reject"] == ApplicationStatus.REJECTED
    state = db_session.get(SyncState, user_id)
    assert state is not None
    assert state.history_id == profile_history == result.history_id
    assert state.initial_sync_done and state.status == "idle" and state.last_error is None
    assert result.mode == "initial"
    assert result.threads_kept == 4 and result.threads_dropped == 1 and result.threads_seen == 5


def test_history_id_is_taken_before_listing(db_session: Session, user_id: uuid.UUID) -> None:
    client = fake()
    before = client.get_profile().history_id

    class Racy(FakeGmailClient):
        def list_threads(self, query, page_token=None):  # type: ignore[no-untyped-def]
            self.add_message("t-late", from_address="jobs@late.example", subject="Application")
            return super().list_threads(query, page_token)

    racy = Racy(OWNER, threads(), now=NOW)
    result = sync_once(db_session, user_id, racy)
    assert result.history_id == before
    assert int(racy.get_profile().history_id) > int(before)


def test_only_threads_within_the_initial_window_and_pagination_handles_each_once(
    db_session: Session, user_id: uuid.UUID
) -> None:
    built = threads()
    built.update({f"t-extra{i}": [m for m in built["t-confirm"]] for i in range(7)})
    built["t-old"] = [
        m.__class__(**{**m.__dict__, "thread_id": "t-old", "sent_at": NOW - 100 * DAY})
        for m in built["t-confirm"]
    ]
    client = FakeGmailClient(OWNER, built, now=NOW, page_size=3)
    result = sync_once(db_session, user_id, client)
    ids = thread_ids(db_session, user_id)
    assert "t-old" not in ids and "t-newsletter" not in ids
    assert len(ids) == 4 + 7
    assert result.threads_seen == 4 + 7 + 1  # newsletter included, old thread out of window
    assert count(db_session, EmailThread, user_id) == 11


def test_running_initial_sync_twice_creates_no_duplicates(
    db_session: Session, user_id: uuid.UUID
) -> None:
    client = fake()
    sync_once(db_session, user_id, client)
    before = (
        count(db_session, EmailThread),
        count(db_session, Application),
        count(db_session, StatusEvent),
    )
    state = db_session.get(SyncState, user_id)
    assert state is not None
    state.initial_sync_done = False
    sync_once(db_session, user_id, client)
    after = (
        count(db_session, EmailThread),
        count(db_session, Application),
        count(db_session, StatusEvent),
    )
    assert before == after


def test_incremental_sync_advances_creates_and_ignores_newsletters(
    db_session: Session, user_id: uuid.UUID
) -> None:
    client = fake()
    first = sync_once(db_session, user_id, client)
    client.add_message(
        "t-confirm",
        from_address="jobs@acme-robotics.example",
        subject="Interview invitation",
        snippet="We would like to schedule an interview",
        sent_at=NOW,
    )
    client.add_message(
        "t-new",
        from_address="jobs@umbrella.example",
        subject="We received your application",
        sent_at=NOW,
    )
    client.add_message(
        "t-news2", from_address="news@promo.example", subject="Big sale", sent_at=NOW
    )
    result = sync_once(db_session, user_id, client)
    assert result.mode == "incremental"
    assert result.threads_seen == 3 and result.threads_dropped == 1
    found = statuses(db_session, user_id)
    assert found["t-confirm"] == ApplicationStatus.INTERVIEW
    assert found["t-new"] == ApplicationStatus.APPLIED
    assert "t-news2" not in thread_ids(db_session, user_id)
    assert int(result.history_id) > int(first.history_id)
    state = db_session.get(SyncState, user_id)
    assert state is not None and state.history_id == result.history_id


def test_incremental_with_no_changes_does_nothing(db_session: Session, user_id: uuid.UUID) -> None:
    client = fake()
    sync_once(db_session, user_id, client)
    result = sync_once(db_session, user_id, client)
    assert result.mode == "incremental" and result.threads_seen == 0


def test_incremental_skips_a_deleted_thread(db_session: Session, user_id: uuid.UUID) -> None:
    client = fake()
    sync_once(db_session, user_id, client)
    client.add_message("t-gone", from_address="jobs@x.example", subject="Application received")
    client.add_message("t-here", from_address="jobs@y.example", subject="Application received")

    class Missing(FakeGmailClient):
        def get_threads(self, thread_ids: list[str]) -> list[ThreadMeta]:
            if "t-gone" in thread_ids:
                raise GmailNotFound("t-gone")
            return super().get_threads(thread_ids)

        def get_thread(self, thread_id: str) -> ThreadMeta:
            if thread_id == "t-gone":
                raise GmailNotFound(thread_id)
            return super().get_thread(thread_id)

    client.__class__ = Missing
    result = sync_once(db_session, user_id, client)
    assert result.threads_seen == 1
    assert "t-here" in thread_ids(db_session, user_id)


def test_history_expired_falls_back_to_full_sync_without_duplicates(
    db_session: Session, user_id: uuid.UUID
) -> None:
    client = fake()
    sync_once(db_session, user_id, client)
    before = (count(db_session, EmailThread), count(db_session, Application))
    client.history_floor = 10**9
    client.fail_next(GmailHistoryExpired("old"))
    result = sync_once(db_session, user_id, client)
    assert result.mode == "fallback_full"
    assert (count(db_session, EmailThread), count(db_session, Application)) == before
    state = db_session.get(SyncState, user_id)
    assert state is not None and state.status == "idle"


def test_auth_revoked_marks_token_and_state_and_stops(
    db_session: Session, user_id: uuid.UUID
) -> None:
    db_session.add(
        OAuthToken(
            user_id=user_id,
            refresh_token_enc=b"x",
            nonce=b"n",
            key_version=1,
            scopes="s",
            status=TokenStatus.ACTIVE,
        )
    )
    db_session.flush()
    client = fake()
    client.revoke()
    with pytest.raises(SyncRevoked):
        run_sync(db_session, user_id, client, CLASSIFIER, NOW, commit=db_session.flush)
    state = db_session.get(SyncState, user_id)
    assert state is not None
    assert (state.status, state.last_error) == ("revoked", "auth_revoked")
    assert not state.initial_sync_done
    assert db_session.get(OAuthToken, user_id).status == TokenStatus.REVOKED  # type: ignore[union-attr]
    assert count(db_session, EmailThread, user_id) == 0


class RateLimitedClient(FakeGmailClient):
    def __init__(self, failures: int) -> None:
        super().__init__(OWNER, threads(), now=NOW)
        self.failures = failures

    def get_profile(self):  # type: ignore[no-untyped-def]
        if self.failures > 0:
            self.failures -= 1
            raise GmailRateLimited
        return super().get_profile()


def test_rate_limit_retries_with_backoff_then_succeeds(
    db_session: Session, user_id: uuid.UUID
) -> None:
    sleeps: list[float] = []
    result = sync_once(db_session, user_id, RateLimitedClient(3), sleep=sleeps.append)
    assert sleeps == [1.0, 2.0, 4.0]
    assert result.threads_kept == 4


def test_other_gmail_error_stores_only_a_stable_code(
    db_session: Session, user_id: uuid.UUID
) -> None:
    client = fake()
    client.fail_next(GmailError("secret subject text"))
    with pytest.raises(SyncFailed):
        run_sync(db_session, user_id, client, CLASSIFIER, NOW, commit=db_session.flush)
    state = db_session.get(SyncState, user_id)
    assert state is not None
    assert (state.status, state.last_error) == ("error", "gmail_error")


def test_snippets_capped_no_recipients_and_drafts_skipped(
    db_session: Session, user_id: uuid.UUID
) -> None:
    client = fake()
    client.add_message(
        "t-long",
        from_address="jobs@long.example",
        subject="Application received",
        snippet="x" * 500,
    )
    client.add_message(
        "t-draft",
        from_address=OWNER,
        subject="Internship application",
        from_user=True,
        label_ids=frozenset({"DRAFT"}),
    )
    sync_once(db_session, user_id, client)
    ids = thread_ids(db_session, user_id)
    assert "t-draft" not in ids and "t-long" in ids
    snippets = list(db_session.scalars(select(EmailThread.snippet)))
    assert snippets and all(len(s) <= 200 for s in snippets)
    columns = {c.name for c in EmailThread.__table__.columns}
    assert not {"to", "cc", "bcc", "recipient"} & columns


def test_user_sent_thread_uses_first_message(db_session: Session, user_id: uuid.UUID) -> None:
    sync_once(db_session, user_id, fake())
    sent = db_session.scalar(select(EmailThread).where(EmailThread.gmail_thread_id == "t-sent"))
    assert sent is not None and sent.from_domain == "mail.example"


def test_syncing_user_b_never_touches_user_a_rows(db_session: Session, user_id: uuid.UUID) -> None:
    other = make_user(db_session)
    sync_once(db_session, user_id, fake())
    snapshot = list(
        db_session.execute(
            select(EmailThread.id, EmailThread.updated_at, EmailThread.snippet).where(
                EmailThread.user_id == user_id
            )
        )
    )
    state_a = db_session.get(SyncState, user_id)
    assert state_a is not None
    updated = state_a.updated_at
    sync_once(db_session, other, fake())
    after = list(
        db_session.execute(
            select(EmailThread.id, EmailThread.updated_at, EmailThread.snippet).where(
                EmailThread.user_id == user_id
            )
        )
    )
    assert snapshot == after
    assert state_a.updated_at == updated
    assert count(db_session, EmailThread, other) == count(db_session, EmailThread, user_id)
    assert statuses(db_session, other) == statuses(db_session, user_id)


class CountingClassifier:
    def __init__(self) -> None:
        self.calls = 0

    def classify(self, inp: ClassificationInput) -> ClassificationResult:
        self.calls += 1
        return CLASSIFIER.classify(inp)


class ExplodingClassifier:
    def classify(self, inp: ClassificationInput) -> ClassificationResult:
        raise RuntimeError("boom subject text")


def force_full_pass(session: Session, user_id: uuid.UUID) -> None:
    """Make the next run an initial pass so every thread is looked at again."""
    state = session.get(SyncState, user_id)
    assert state is not None
    state.initial_sync_done = False


def run_counted(
    session: Session, user_id: uuid.UUID, client: FakeGmailClient, *, force: bool = False
) -> CountingClassifier:
    classifier = CountingClassifier()
    run_sync(session, user_id, client, classifier, NOW, commit=session.flush, force=force)
    return classifier


def test_unchanged_threads_are_not_reclassified_but_force_reprocesses(
    db_session: Session, user_id: uuid.UUID
) -> None:
    client = fake()
    sync_once(db_session, user_id, client)
    force_full_pass(db_session, user_id)
    assert run_counted(db_session, user_id, client).calls == 0
    force_full_pass(db_session, user_id)
    assert run_counted(db_session, user_id, client, force=True).calls == 4


def test_pipeline_version_change_reprocesses_threads(
    db_session: Session, user_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = fake()
    sync_once(db_session, user_id, client)
    monkeypatch.setattr(sync, "PIPELINE_VERSION", "2")
    force_full_pass(db_session, user_id)
    assert run_counted(db_session, user_id, client).calls == 4
    versions = set(
        db_session.scalars(
            select(EmailThread.pipeline_version).where(EmailThread.user_id == user_id)
        )
    )
    assert versions == {"2"}


def test_fallback_full_reprocesses_unchanged_threads(
    db_session: Session, user_id: uuid.UUID
) -> None:
    client = fake()
    sync_once(db_session, user_id, client)
    client.fail_next(GmailHistoryExpired("old"))
    assert run_counted(db_session, user_id, client).calls == 4


def test_identical_classification_is_not_appended_twice(
    db_session: Session, user_id: uuid.UUID
) -> None:
    client = fake()
    sync_once(db_session, user_id, client)
    before = count(db_session, Classification)
    force_full_pass(db_session, user_id)
    run_counted(db_session, user_id, client, force=True)
    assert count(db_session, Classification) == before


def test_history_id_never_moves_backwards() -> None:
    assert sync._newest("2000", "1000") == "2000"
    assert sync._newest("999", "1000") == "1000"
    assert sync._newest(None, "5") == "5"


def test_retry_after_is_clamped_to_sixty_seconds(db_session: Session, user_id: uuid.UUID) -> None:
    class Slow(FakeGmailClient):
        tripped = False

        def get_profile(self):  # type: ignore[no-untyped-def]
            if not self.tripped:
                self.tripped = True
                raise GmailRateLimited(retry_after=500)
            return super().get_profile()

    sleeps: list[float] = []
    sync_once(db_session, user_id, Slow(OWNER, threads(), now=NOW), sleep=sleeps.append)
    assert sleeps == [60.0]


def test_lease_is_renewed_after_each_batch(
    db_session: Session, user_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sync, "BATCH_SIZE", 1)
    later = NOW + timedelta(minutes=10)
    seen: list[datetime | None] = []

    class Spy:
        def classify(self, inp: ClassificationInput) -> ClassificationResult:
            state = db_session.get(SyncState, user_id)
            seen.append(state.lease_expires_at if state else None)
            return CLASSIFIER.classify(inp)

    run_sync(db_session, user_id, fake(), Spy(), NOW, commit=db_session.flush, clock=lambda: later)
    assert seen[0] == NOW + timedelta(minutes=15)
    assert seen[-1] == later + timedelta(minutes=15)


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine(get_settings().database_url)
    yield eng
    eng.dispose()


@pytest.fixture
def committed_user(engine: Engine) -> Iterator[uuid.UUID]:
    """A user committed for real; deleting it cascades to every row the test created."""
    with Session(engine) as session:
        uid = make_user(session)
        session.commit()
    yield uid
    with Session(engine) as session:
        session.execute(delete(User).where(User.id == uid))
        session.commit()


def real_sync(engine: Engine, uid: uuid.UUID, client: FakeGmailClient, now: datetime = NOW):  # type: ignore[no-untyped-def]
    with Session(engine) as session:
        return run_sync(session, uid, client, CLASSIFIER, now)


def read_state(engine: Engine, uid: uuid.UUID) -> SyncState:
    with Session(engine) as session:
        state = session.get(SyncState, uid)
        assert state is not None
        return state


def test_real_commit_path_persists_work_and_releases_lease(
    engine: Engine, committed_user: uuid.UUID
) -> None:
    assert isinstance(real_sync(engine, committed_user, fake()), SyncResult)
    with Session(engine) as other:
        assert thread_ids(other, committed_user) == {
            "t-confirm",
            "t-interview",
            "t-reject",
            "t-sent",
        }
    state = read_state(engine, committed_user)
    assert (state.status, state.lease_expires_at) == ("idle", None)


def test_second_concurrent_claim_returns_already_running_then_released_lease_reclaims(
    engine: Engine, committed_user: uuid.UUID
) -> None:
    outcomes: list[object] = []

    class Reentrant(FakeGmailClient):
        def list_threads(self, query, page_token=None):  # type: ignore[no-untyped-def]
            outcomes.append(real_sync(engine, committed_user, fake()))
            return super().list_threads(query, page_token)

    assert isinstance(
        real_sync(engine, committed_user, Reentrant(OWNER, threads(), now=NOW)), SyncResult
    )
    assert outcomes == [SyncAlreadyRunning()]
    # released: an immediate new sync is accepted
    assert isinstance(real_sync(engine, committed_user, fake()), SyncResult)


def test_stale_lease_from_a_crashed_sync_is_reclaimed_after_expiry(
    engine: Engine, committed_user: uuid.UUID
) -> None:
    with Session(engine) as session:
        session.add(
            SyncState(
                user_id=committed_user,
                status="running",
                started_at=NOW,
                lease_expires_at=NOW + timedelta(minutes=15),
            )
        )
        session.commit()
    assert real_sync(engine, committed_user, fake()) == SyncAlreadyRunning()
    after = NOW + timedelta(minutes=16)
    assert isinstance(real_sync(engine, committed_user, fake(), after), SyncResult)


def test_unexpected_error_records_internal_error_and_releases_lease(
    engine: Engine, committed_user: uuid.UUID
) -> None:
    with Session(engine) as session, pytest.raises(RuntimeError):
        run_sync(session, committed_user, fake(), ExplodingClassifier(), NOW)
    state = read_state(engine, committed_user)
    assert (state.status, state.last_error, state.lease_expires_at) == (
        "error",
        "internal_error",
        None,
    )
    assert isinstance(real_sync(engine, committed_user, fake()), SyncResult)
