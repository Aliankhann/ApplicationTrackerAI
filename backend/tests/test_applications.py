import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DataError, IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from alembic import command
from app.config import get_settings
from app.errors import NotFound
from app.models import Application, Classification, EmailThread, StatusEvent, User
from app.providers.classifier.types import ClassificationResult, Label
from app.providers.gmail.types import MessageMeta, ThreadMeta
from app.repositories import applications as apps_repo
from app.repositories import threads as threads_repo
from app.services import applications as svc
from app.services.classification import ApplicationStatus
from app.services.extraction import Extracted

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
NO_EXTRACT = Extracted(None, None, None, None)


def make_user(session: Session) -> User:
    user = User(google_sub=uuid.uuid4().hex, email="u@example.test")
    session.add(user)
    session.flush()
    return user


def msg(i: int, from_user: bool = False, labels: frozenset[str] = frozenset()) -> MessageMeta:
    return MessageMeta(
        message_id=f"m{i}",
        thread_id="t1",
        from_address="jobs@acme.example",
        from_name="Acme",
        subject="s",
        snippet="x",
        sent_at=T0 + timedelta(hours=i),
        from_user=from_user,
        rfc822_message_id=None,
        label_ids=labels,
    )


def meta(*messages: MessageMeta, thread_id: str = "t1") -> ThreadMeta:
    return ThreadMeta(thread_id=thread_id, history_id="h", messages=messages or (msg(0),))


def make_thread(session: Session, user: User, thread_id: str = "t1") -> EmailThread:
    return threads_repo.upsert_thread(
        session, user.id, meta(thread_id=thread_id), "Subject", "acme.example", "snip"
    )


def result(
    label: Label | None, rule_id: str | None = "r1", review: bool = False
) -> ClassificationResult:
    return ClassificationResult(label, 0.9, "rules", rule_id, review)


def record(
    session: Session,
    user: User,
    thread: EmailThread,
    res: ClassificationResult,
    extracted: Extracted = NO_EXTRACT,
    now: datetime = NOW,
) -> Application | None:
    return svc.record_classification(session, user.id, thread, res, extracted, now)


def events(session: Session, user: User, app: Application) -> list[StatusEvent]:
    return apps_repo.list_events(session, user.id, app.id)


def test_ac1_migration_0003_up_down_and_snippet_check(db_session: Session) -> None:
    user = make_user(db_session)
    row = EmailThread(
        user_id=user.id,
        gmail_thread_id="long",
        subject="s",
        from_domain="d",
        snippet="x" * 201,
        first_message_at=T0,
        last_message_at=T0,
        last_sender_is_user=False,
        message_count=1,
    )
    db_session.add(row)
    with pytest.raises((IntegrityError, DataError)):
        db_session.flush()


def test_ac1_snippet_check_constraint_exists(db_session: Session) -> None:
    found = db_session.execute(
        text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
        {"n": "ck_email_threads_snippet_max_200"},
    ).scalar()
    assert found is not None and "200" in found


def _alembic_config() -> Config:
    root = Path(__file__).parent.parent
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    return cfg


def test_ac1_migration_0003_downgrades_and_upgrades(monkeypatch: pytest.MonkeyPatch) -> None:
    """Runs on a throwaway database; the shared test database is never touched."""
    base = make_url(get_settings().database_url)
    name = f"tracker_migtest_{uuid.uuid4().hex[:12]}"
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except ProgrammingError:
        admin.dispose()
        pytest.skip("CREATE DATABASE not permitted: run ALTER USER tracker CREATEDB")
    try:
        monkeypatch.setenv("DATABASE_URL", base.set(database=name).render_as_string(False))
        get_settings.cache_clear()
        cfg = _alembic_config()
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def test_ac2_upsert_thread_is_idempotent_and_truncates_snippet(db_session: Session) -> None:
    user = make_user(db_session)
    first = threads_repo.upsert_thread(db_session, user.id, meta(), "S", "d", "y" * 500)
    second = threads_repo.upsert_thread(db_session, user.id, meta(msg(0), msg(1)), "S2", "d", "z")
    assert first.id == second.id
    assert second.message_count == 2 and second.snippet == "z"
    assert first.snippet == "z"
    count = db_session.scalar(select(func.count()).select_from(EmailThread))
    assert count == 1
    long = threads_repo.upsert_thread(
        db_session, user.id, meta(thread_id="t2"), "S", "d", "y" * 500
    )
    assert len(long.snippet) == 200


def test_ac2_draft_messages_do_not_count_as_last_sender(db_session: Session) -> None:
    user = make_user(db_session)
    thread = threads_repo.upsert_thread(
        db_session,
        user.id,
        meta(msg(0), msg(1, from_user=True, labels=frozenset({"DRAFT"}))),
        "S",
        "d",
        "x",
    )
    assert thread.last_sender_is_user is False
    assert thread.last_message_at == T0
    assert thread.message_count == 1


def test_ac3_confirmation_interview_rejection_one_application_three_events(
    db_session: Session,
) -> None:
    user = make_user(db_session)
    thread = make_thread(db_session, user)
    app = record(db_session, user, thread, result(Label.CONFIRMATION, "conf"))
    record(db_session, user, thread, result(Label.INTERVIEW, "intv"), now=NOW + timedelta(hours=1))
    final = record(
        db_session, user, thread, result(Label.REJECTION, "rej"), now=NOW + timedelta(hours=2)
    )
    assert app is not None and final is app
    assert app.status == ApplicationStatus.REJECTED
    assert app.applied_at == thread.first_message_at
    timeline = events(db_session, user, app)
    assert [e.reason for e in timeline] == ["created", "classifier:intv", "classifier:rej"]
    assert [e.to_status for e in timeline] == [
        ApplicationStatus.APPLIED,
        ApplicationStatus.INTERVIEW,
        ApplicationStatus.REJECTED,
    ]
    assert db_session.scalar(select(func.count()).select_from(Application)) == 1


def test_ac3_duplicate_processing_creates_no_second_application_or_event(
    db_session: Session,
) -> None:
    user = make_user(db_session)
    thread = make_thread(db_session, user)
    app = record(db_session, user, thread, result(Label.CONFIRMATION))
    again = record(db_session, user, thread, result(Label.CONFIRMATION))
    assert app is again and app is not None
    assert len(events(db_session, user, app)) == 1
    assert db_session.scalar(select(func.count()).select_from(Application)) == 1


def test_ac3_llm_result_uses_llm_reason(db_session: Session) -> None:
    user = make_user(db_session)
    thread = make_thread(db_session, user)
    app = record(db_session, user, thread, result(Label.CONFIRMATION))
    llm = ClassificationResult(Label.OFFER, 0.9, "llm", None, False, "m1")
    record(db_session, user, thread, llm, now=NOW + timedelta(hours=1))
    assert app is not None
    assert events(db_session, user, app)[-1].reason == "classifier:llm"


def test_ac4_backward_moves_are_ignored(db_session: Session) -> None:
    user = make_user(db_session)
    thread = make_thread(db_session, user)
    record(db_session, user, thread, result(Label.INTERVIEW, "intv"))
    app = record(db_session, user, thread, result(Label.CONFIRMATION, "conf"))
    assert app is not None
    assert app.status == ApplicationStatus.INTERVIEW
    assert app.applied_at is None
    assert [e.reason for e in events(db_session, user, app)] == ["created"]


@pytest.mark.parametrize(
    "res",
    [
        result(Label.IRRELEVANT),
        result(Label.RECRUITER_MESSAGE),
        result(Label.OFFER, review=True),
        result(None),
    ],
)
def test_ac5_unactionable_results_create_no_application(
    db_session: Session, res: ClassificationResult
) -> None:
    user = make_user(db_session)
    thread = make_thread(db_session, user)
    assert record(db_session, user, thread, res) is None
    assert db_session.scalar(select(func.count()).select_from(Application)) == 0
    assert db_session.scalar(select(func.count()).select_from(Classification)) == 1


def test_ac5_unactionable_result_only_bumps_last_activity(db_session: Session) -> None:
    user = make_user(db_session)
    thread = make_thread(db_session, user)
    app = record(db_session, user, thread, result(Label.CONFIRMATION))
    later = NOW + timedelta(days=1)
    same = record(db_session, user, thread, result(Label.IRRELEVANT), now=later)
    assert app is not None and same is app
    assert app.status == ApplicationStatus.APPLIED
    assert app.last_activity_at == later
    assert len(events(db_session, user, app)) == 1


def test_ac6_locked_application_ignores_classifier_status(db_session: Session) -> None:
    user = make_user(db_session)
    thread = make_thread(db_session, user)
    app = record(db_session, user, thread, result(Label.CONFIRMATION))
    assert app is not None
    svc.set_status_manually(
        db_session, user.id, app.id, ApplicationStatus.INTERVIEW, NOW + timedelta(minutes=1)
    )
    later = NOW + timedelta(days=1)
    record(db_session, user, thread, result(Label.REJECTION, "rej"), now=later)
    assert app.status == ApplicationStatus.INTERVIEW
    assert app.last_activity_at == later
    assert [e.reason for e in events(db_session, user, app)] == ["created", "manual"]


def test_ac6_set_status_manually_locks_and_writes_manual_event(db_session: Session) -> None:
    user = make_user(db_session)
    thread = make_thread(db_session, user)
    app = record(db_session, user, thread, result(Label.OFFER))
    assert app is not None
    updated = svc.set_status_manually(
        db_session, user.id, app.id, ApplicationStatus.APPLIED, NOW + timedelta(minutes=1)
    )
    assert updated.status == ApplicationStatus.APPLIED and updated.status_locked
    last = events(db_session, user, app)[-1]
    assert (last.reason, last.from_status, last.to_status) == (
        "manual",
        ApplicationStatus.OFFER,
        ApplicationStatus.APPLIED,
    )


def test_ac7_other_user_cannot_read_or_change_application(db_session: Session) -> None:
    a, b = make_user(db_session), make_user(db_session)
    thread = make_thread(db_session, a)
    app = record(db_session, a, thread, result(Label.CONFIRMATION))
    assert app is not None
    assert apps_repo.get(db_session, b.id, app.id) is None
    assert apps_repo.get_for_thread(db_session, b.id, thread.id) is None
    assert apps_repo.list_events(db_session, b.id, app.id) == []
    with pytest.raises(NotFound):
        svc.set_status_manually(db_session, b.id, app.id, ApplicationStatus.OFFER, NOW)
    with pytest.raises(NotFound):
        record(db_session, b, thread, result(Label.OFFER))
    assert app.status == ApplicationStatus.APPLIED and not app.status_locked


def test_ac7_same_gmail_thread_id_for_two_users_creates_separate_rows(db_session: Session) -> None:
    a, b = make_user(db_session), make_user(db_session)
    ta, tb = make_thread(db_session, a), make_thread(db_session, b)
    assert ta.id != tb.id


def test_ac8_company_and_role_filled_once_never_overwritten(db_session: Session) -> None:
    user = make_user(db_session)
    thread = make_thread(db_session, user)
    app = record(db_session, user, thread, result(Label.CONFIRMATION))
    assert app is not None
    assert app.company is None
    record(db_session, user, thread, result(Label.INTERVIEW), Extracted("Acme", None, "s", None))
    assert app.company == "Acme"
    assert app.role is None
    record(db_session, user, thread, result(Label.OFFER), Extracted("Other", "Intern", "s", "s"))
    assert app.company == "Acme"
    assert app.role == "Intern"


def test_ac9_deleting_user_cascades_everything(db_session: Session) -> None:
    user = make_user(db_session)
    thread = make_thread(db_session, user)
    record(db_session, user, thread, result(Label.CONFIRMATION))
    record(db_session, user, thread, result(Label.INTERVIEW))
    db_session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user.id})
    for model in (EmailThread, Classification, Application, StatusEvent):
        assert db_session.scalar(select(func.count()).select_from(model)) == 0


def test_event_order_is_insertion_order_when_timestamps_tie(db_session: Session) -> None:
    user = make_user(db_session)
    thread = make_thread(db_session, user)
    app = record(db_session, user, thread, result(Label.CONFIRMATION))
    record(db_session, user, thread, result(Label.INTERVIEW), now=NOW)
    record(db_session, user, thread, result(Label.OFFER), now=NOW)
    assert app is not None
    got = [e.to_status for e in events(db_session, user, app)]
    assert got == [ApplicationStatus.APPLIED, ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER]


def test_race_unique_conflict_on_create_returns_existing_application(db_session: Session) -> None:
    user = make_user(db_session)
    thread = make_thread(db_session, user)
    app = record(db_session, user, thread, result(Label.CONFIRMATION))
    again = svc._try_create(db_session, user.id, thread, ApplicationStatus.APPLIED, NO_EXTRACT, NOW)
    assert again is None
    assert apps_repo.get_for_thread(db_session, user.id, thread.id) is app


def test_race_concurrent_sessions_create_one_application() -> None:
    engine = create_engine(get_settings().database_url)
    first, second = Session(engine), Session(engine)
    errors: list[Exception] = []
    try:
        user = make_user(first)
        thread = make_thread(first, user)
        first.commit()
        record(first, user, thread, result(Label.CONFIRMATION))  # uncommitted, holds the lock

        def other() -> None:
            try:
                other_thread = threads_repo.upsert_thread(
                    second, user.id, meta(), "Subject", "acme.example", "snip"
                )
                record(second, user, other_thread, result(Label.INTERVIEW), now=NOW)
                second.commit()
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=other)
        worker.start()
        time.sleep(0.5)
        first.commit()
        worker.join(timeout=10)
        assert not worker.is_alive()
        assert errors == []
        with Session(engine) as check:
            rows = check.scalars(select(Application).where(Application.user_id == user.id)).all()
            assert len(rows) == 1 and rows[0].status == ApplicationStatus.INTERVIEW
    finally:
        first.rollback()
        second.rollback()
        first.execute(text("DELETE FROM users WHERE google_sub = :s"), {"s": user.google_sub})
        first.commit()
        first.close()
        second.close()
        engine.dispose()


def test_add_classification_rejects_other_users_thread(db_session: Session) -> None:
    a, b = make_user(db_session), make_user(db_session)
    thread = make_thread(db_session, a)
    with pytest.raises(NotFound):
        threads_repo.add_classification(db_session, b.id, thread, result(Label.OFFER))


def test_naive_now_is_rejected(db_session: Session) -> None:
    user = make_user(db_session)
    thread = make_thread(db_session, user)
    naive = datetime(2026, 11, 18, 12, 0)
    with pytest.raises(ValueError):
        record(db_session, user, thread, result(Label.OFFER), now=naive)
    app = record(db_session, user, thread, result(Label.OFFER))
    assert app is not None
    with pytest.raises(ValueError):
        svc.set_status_manually(db_session, user.id, app.id, ApplicationStatus.APPLIED, naive)


def test_manual_same_status_locks_without_event(db_session: Session) -> None:
    user = make_user(db_session)
    thread = make_thread(db_session, user)
    app = record(db_session, user, thread, result(Label.INTERVIEW))
    assert app is not None
    svc.set_status_manually(db_session, user.id, app.id, ApplicationStatus.INTERVIEW, NOW)
    assert app.status_locked
    assert [e.reason for e in events(db_session, user, app)] == ["created"]


def test_manual_move_to_applied_sets_applied_at_when_null(db_session: Session) -> None:
    user = make_user(db_session)
    thread = make_thread(db_session, user)
    app = record(db_session, user, thread, result(Label.INTERVIEW))
    assert app is not None and app.applied_at is None
    later = NOW + timedelta(minutes=1)
    svc.set_status_manually(db_session, user.id, app.id, ApplicationStatus.APPLIED, later)
    assert app.applied_at == thread.first_message_at


def test_long_values_are_truncated_before_insert(db_session: Session) -> None:
    user = make_user(db_session)
    thread = threads_repo.upsert_thread(db_session, user.id, meta(), "s" * 2000, "d" * 400, "x")
    assert len(thread.from_domain) == 255 and len(thread.subject) == 998
    extracted = Extracted("c" * 200, "r" * 300, None, None)
    app = record(db_session, user, thread, result(Label.CONFIRMATION), extracted)
    assert app is not None
    assert app.company is not None and len(app.company) == 80
    assert app.role is not None and len(app.role) == 120
