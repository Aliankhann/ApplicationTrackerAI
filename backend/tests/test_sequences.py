import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import InvalidOperation, NotFound
from app.models import Application, FollowUpTask, Sequence, User
from app.repositories import sequences as repo
from app.services.classification import ApplicationStatus
from app.services.sequences import DEFAULT_STEPS, parse_steps, parse_stored_steps

OK = {"delay_days": 3, "template": "Following up on {role}."}


def make_user(session: Session) -> User:
    user = User(google_sub=uuid.uuid4().hex, email="u@example.test")
    session.add(user)
    session.flush()
    return user


def test_ac1_one_default_per_user_enforced_by_database(db_session: Session) -> None:
    user = make_user(db_session)
    db_session.add(Sequence(user_id=user.id, name="a", steps=[OK], is_default=True))
    db_session.flush()
    db_session.add(Sequence(user_id=user.id, name="b", steps=[OK], is_default=False))
    db_session.flush()
    db_session.begin_nested()
    db_session.add(Sequence(user_id=user.id, name="c", steps=[OK], is_default=True))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_ac2_get_or_create_default_is_idempotent(db_session: Session) -> None:
    user, other = make_user(db_session), make_user(db_session)
    first = repo.get_or_create_default(db_session, user.id)
    second = repo.get_or_create_default(db_session, user.id)
    assert first.id == second.id and first.is_default
    assert [s["delay_days"] for s in first.steps] == [7, 14]
    assert len(DEFAULT_STEPS) == 2
    assert repo.get_or_create_default(db_session, other.id).id != first.id
    assert len(repo.list_for_user(db_session, user.id)) == 1


@pytest.mark.parametrize(
    ("steps", "message"),
    [
        ([{**OK, "delay_days": 0}], "greater than or equal to 1"),
        ([{**OK, "delay_days": 61}], "less than or equal to 60"),
        ([], "at least 1"),
        ([{**OK, "delay_days": d} for d in range(1, 7)], "at most 5"),
        ([OK, OK], "strictly increasing"),
        ([{**OK, "max_attempts": 0}], "greater than or equal to 1"),
        ([{**OK, "max_attempts": 4}], "less than or equal to 3"),
        ([{**OK, "template": ""}], "at least 1"),
        ([{**OK, "template": "x" * 2001}], "at most 2000"),
        ([{**OK, "template": "Hi {nope}"}], "Unknown placeholder"),
        ([{**OK, "template": "Hi {role"}], "braces"),
        ([{**OK, "template": "Hi role}"}], "braces"),
        ([{**OK, "template": "Hi <b>there</b>"}], "HTML"),
    ],
)
def test_ac3_step_validation_rejects_with_clear_error(
    steps: list[dict[str, object]], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        parse_steps(steps)


def test_ac3_valid_steps_accepted_with_default_attempts() -> None:
    steps = parse_steps([OK, {"delay_days": 10, "template": "{company} {your_name}"}])
    assert [s.max_attempts for s in steps] == [1, 1]


def test_ac3_repository_rejects_invalid_steps(db_session: Session) -> None:
    user = make_user(db_session)
    with pytest.raises(ValidationError):
        repo.create(db_session, user.id, "bad", [{"delay_days": 1, "template": "<i>x</i>"}])


def test_ac4_new_default_unsets_previous(db_session: Session) -> None:
    user = make_user(db_session)
    old = repo.get_or_create_default(db_session, user.id)
    new = repo.create(db_session, user.id, "new", [OK], make_default=True)
    assert new.is_default and not old.is_default
    third = repo.create(db_session, user.id, "third", [OK])
    repo.update(db_session, user.id, third.id, make_default=True, tone="warm", name="t")
    assert third.is_default and not new.is_default
    assert third.tone == "warm" and third.name == "t"
    defaults = [s for s in repo.list_for_user(db_session, user.id) if s.is_default]
    assert len(defaults) == 1


def test_ac4_other_users_sequence_is_not_found(db_session: Session) -> None:
    a, b = make_user(db_session), make_user(db_session)
    seq = repo.create(db_session, a.id, "mine", [OK])
    with pytest.raises(NotFound):
        repo.get(db_session, b.id, seq.id)
    with pytest.raises(NotFound):
        repo.update(db_session, b.id, seq.id, name="hacked")
    assert repo.list_for_user(db_session, b.id) == []
    assert seq.name == "mine"


def test_ac8_deleting_user_cascades_sequences_and_tasks(db_session: Session) -> None:
    user = make_user(db_session)
    seq = repo.get_or_create_default(db_session, user.id)
    app = Application(
        user_id=user.id,
        status=ApplicationStatus.APPLIED,
        last_activity_at=datetime.now(UTC),
    )
    db_session.add(app)
    db_session.flush()
    db_session.add(
        FollowUpTask(
            application_id=app.id,
            sequence_id=seq.id,
            step_index=0,
            due_at=datetime.now(UTC) + timedelta(days=7),
        )
    )
    db_session.flush()
    db_session.execute(delete(User).where(User.id == user.id))
    db_session.expire_all()
    for model in (Sequence, FollowUpTask):
        assert db_session.scalar(select(func.count()).select_from(model)) == 0


def test_ac8_task_state_check_and_unique_step(db_session: Session) -> None:
    user = make_user(db_session)
    app = Application(
        user_id=user.id, status=ApplicationStatus.APPLIED, last_activity_at=datetime.now(UTC)
    )
    db_session.add(app)
    db_session.flush()
    due = datetime.now(UTC)
    db_session.add(FollowUpTask(application_id=app.id, step_index=0, due_at=due))
    db_session.flush()
    for kwargs in ({"step_index": 0}, {"step_index": 1, "state": "bogus"}):
        db_session.begin_nested()
        db_session.add(FollowUpTask(application_id=app.id, due_at=due, **kwargs))
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()


def test_ac3_name_and_tone_validated_in_python(db_session: Session) -> None:
    user = make_user(db_session)
    for name in ("", "   ", "\u202e\x00", "n" * 81):
        with pytest.raises(ValueError, match="Name"):
            repo.create(db_session, user.id, name, [OK])
    with pytest.raises(ValueError, match="tone"):
        repo.create(db_session, user.id, "n", [OK], tone="loud")
    seq = repo.create(db_session, user.id, "  My\u200b  plan \n", [OK], tone="formal")
    assert seq.name == "My plan"
    with pytest.raises(ValueError, match="tone"):
        repo.update(db_session, user.id, seq.id, tone="loud")
    with pytest.raises(ValueError, match="Name"):
        repo.update(db_session, user.id, seq.id, name=" ")


def test_ac4_cannot_unset_the_only_default(db_session: Session) -> None:
    user = make_user(db_session)
    default = repo.get_or_create_default(db_session, user.id)
    with pytest.raises(InvalidOperation):
        repo.update(db_session, user.id, default.id, make_default=False)
    assert repo.get_or_create_default(db_session, user.id).id == default.id
    assert len(repo.list_for_user(db_session, user.id)) == 1
    other = repo.create(db_session, user.id, "other", [OK])
    repo.update(db_session, user.id, other.id, make_default=False)  # not the default: no-op


def test_ac3_parse_stored_steps_returns_none_for_invalid_json() -> None:
    assert parse_stored_steps([OK]) is not None
    for bad in (None, "x", [], [{"delay_days": 0, "template": "x"}], [{"template": "{bad}"}]):
        assert parse_stored_steps(bad) is None


def test_ac4_concurrent_default_writers_do_not_raise_integrity_error() -> None:
    engine = create_engine(get_settings().database_url)
    with Session(engine) as setup:
        user = make_user(setup)
        setup.commit()
        user_id = user.id
    errors: list[BaseException] = []
    ids: list[uuid.UUID] = []
    barrier = threading.Barrier(2)

    def worker(kind: str) -> None:
        try:
            with Session(engine) as session:
                barrier.wait(timeout=5)
                if kind == "get":
                    ids.append(repo.get_or_create_default(session, user_id).id)
                else:
                    ids.append(repo.create(session, user_id, kind, [OK], make_default=True).id)
                session.commit()
        except BaseException as exc:
            errors.append(exc)

    try:
        for kinds in (("get", "get"), ("a", "b"), ("get", "c")):
            threads = [threading.Thread(target=worker, args=(k,)) for k in kinds]
            barrier = threading.Barrier(2)
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)
        assert errors == []
        with Session(engine) as check:
            defaults = [s for s in repo.list_for_user(check, user_id) if s.is_default]
            assert len(defaults) == 1
    finally:
        with Session(engine) as cleanup:
            cleanup.execute(delete(User).where(User.id == user_id))
            cleanup.commit()
        engine.dispose()
