"""Two-phase invite claim: expiry cleanup, cap races, and the existing-user migration."""

import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, delete, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from alembic import command
from app.config import Settings, get_settings
from app.jobs import maintenance
from app.models import AuditLog, InviteCode, User, UserSession
from app.providers.google.oidc import Identity
from app.repositories import invite_codes
from app.security.invite_codes import generate_code, hash_code
from app.services import signin
from tests.test_applications import _alembic_config
from tests.test_gmail_connect import CLAIM, HOLD, pending_user
from tests.test_sessions import T0, Env, env  # noqa: F401

AFTER_CLAIM = T0 + CLAIM + timedelta(minutes=1)


def rows(db: Session, model: type, **where: object) -> int:
    stmt = select(func.count()).select_from(model)
    for column, value in where.items():
        stmt = stmt.where(getattr(model, column) == value)
    return db.scalar(stmt) or 0


def test_cleanup_deletes_a_pending_user_past_24h_with_all_rows_and_reopens_the_code(
    env: Env,  # noqa: F811
) -> None:
    user, invite = pending_user(env)
    env.login(user)
    env.db.flush()
    assert maintenance.run(env.db, T0 + timedelta(hours=23)) is not None
    assert env.db.get(User, user.id) is not None  # still inside its 24 hours
    counts = maintenance.run(env.db, AFTER_CLAIM)
    assert counts["pending_users"] == 1
    env.db.expire_all()
    assert env.db.get(User, user.id) is None
    assert rows(env.db, UserSession, user_id=user.id) == 0
    assert rows(env.db, AuditLog, user_id=user.id) == 0
    assert invite.claimed_by_user_id is None and invite.claimed_until is None
    assert invite_codes.state_of(invite, AFTER_CLAIM) == "available"
    # Someone else can now take and claim the very same code.
    other = env.user(setup_completed_at=None)
    assert invite_codes.try_hold(env.db, invite.id, "new", AFTER_CLAIM, HOLD).value == "held"
    assert invite_codes.claim(env.db, invite.id, "new", other.id, AFTER_CLAIM, CLAIM)


def test_cleanup_keeps_completed_allowlisted_and_unexpired_pending_users(env: Env) -> None:  # noqa: F811
    done = env.user()
    done_invite = invite_codes.create(env.db, hash_code(generate_code()), T0 + timedelta(days=9))
    done_invite.used_at, done_invite.used_by_user_id = T0, done.id
    allowlisted = env.user()  # completed, no code at all
    fresh, fresh_invite = pending_user(env)
    env.db.flush()
    maintenance.run(env.db, T0 + timedelta(hours=1))
    maintenance.run(env.db, AFTER_CLAIM - timedelta(minutes=2))
    env.db.expire_all()
    for user in (done, allowlisted, fresh):
        assert env.db.get(User, user.id) is not None
    assert done_invite.used_by_user_id == done.id and fresh_invite.claimed_by_user_id == fresh.id


def test_cleanup_keeps_an_operator_email_binding_on_the_released_code(env: Env) -> None:  # noqa: F811
    _, invite = pending_user(env)
    invite.created_for_email = "intended@example.test"
    env.db.flush()
    maintenance.run(env.db, AFTER_CLAIM)
    env.db.refresh(invite)
    assert invite.created_for_email == "intended@example.test"


def test_cleanup_clears_expired_holds_only(env: Env) -> None:  # noqa: F811
    old = invite_codes.create(env.db, hash_code(generate_code()), T0 + timedelta(days=1))
    live = invite_codes.create(env.db, hash_code(generate_code()), T0 + timedelta(days=1))
    invite_codes.try_hold(env.db, old.id, "a", T0, HOLD)
    invite_codes.try_hold(env.db, live.id, "b", T0 + timedelta(minutes=9), HOLD)
    counts = maintenance.run(env.db, T0 + timedelta(minutes=11))
    env.db.refresh(old)
    env.db.refresh(live)
    assert counts["invite_holds"] >= 1
    assert old.held_until is None and old.hold_token_hash is None
    assert live.held_until is not None


def test_daily_maintenance_runs_the_cleanup(env: Env) -> None:  # noqa: F811
    user, invite = pending_user(env)
    assert maintenance.run_daily(env.db, AFTER_CLAIM) is True
    env.db.expire_all()
    assert env.db.get(User, user.id) is None and invite.claimed_by_user_id is None


def test_a_signup_frees_a_lapsed_claim_before_taking_the_slot(env: Env) -> None:  # noqa: F811
    _, invite = pending_user(env)
    settings = Settings(max_users=invite_codes.slots_in_use(env.db, AFTER_CLAIM) + 1)
    invite_codes.try_hold(env.db, invite.id, "new", AFTER_CLAIM, HOLD)
    identity = Identity("sub-new", "new@example.test", True)
    user = signin.admit(env.db, identity, "signup", (invite.id, "new"), settings, AFTER_CLAIM)
    env.db.flush()
    env.db.refresh(invite)
    assert invite.claimed_by_user_id == user.id  # one pending user, not two orphans
    assert rows(env.db, User, email="u@example.test") == 0


# --- cap races (two real connections) -------------------------------------------------------


def test_two_signups_racing_for_the_last_slot_never_exceed_the_cap() -> None:
    base = get_settings()
    engine = create_engine(base.database_url)
    with Session(engine) as setup:
        baseline = invite_codes.slots_in_use(setup, T0)
        ids = []
        for token in ("a", "b"):
            invite = invite_codes.create(setup, hash_code(generate_code()), T0 + timedelta(days=1))
            invite_codes.try_hold(setup, invite.id, token, T0, HOLD)
            ids.append(invite.id)
        setup.commit()
    settings = Settings(max_users=baseline + 1)  # one free slot, two people want it
    sessions = {"a": Session(engine), "b": Session(engine)}
    subs = {n: f"cap-{uuid.uuid4().hex}" for n in sessions}
    outcomes: dict[str, str] = {}
    release = threading.Event()

    def attempt(name: str, invite_id: uuid.UUID, wait: bool) -> None:
        identity = Identity(subs[name], f"{name}@example.test", True)
        try:
            signin.admit(sessions[name], identity, "signup", (invite_id, name), settings, T0)
            if wait:
                release.wait(timeout=5)
            sessions[name].commit()
            outcomes[name] = "in"
        except signin.SignInRejected as exc:
            sessions[name].rollback()
            outcomes[name] = exc.code

    first = threading.Thread(target=attempt, args=("a", ids[0], True))
    first.start()
    time.sleep(0.3)
    second = threading.Thread(target=attempt, args=("b", ids[1], False))
    second.start()
    threading.Timer(0.5, release.set).start()
    first.join(10)
    second.join(10)
    try:
        assert sorted(outcomes.values()) == ["in", "not_invited"]
        with Session(engine) as check:
            assert invite_codes.slots_in_use(check, T0) == baseline + 1
    finally:
        for session in sessions.values():
            session.close()
        with Session(engine) as cleanup:
            cleanup.execute(delete(InviteCode).where(InviteCode.id.in_(ids)))
            cleanup.execute(delete(User).where(User.google_sub.in_(subs.values())))
            cleanup.commit()
        engine.dispose()


# --- migration 0014 -------------------------------------------------------------------------


@contextmanager
def throwaway_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
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
        yield
    finally:
        get_settings.cache_clear()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def test_migration_0014_marks_existing_users_complete_and_keeps_used_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with throwaway_database(monkeypatch):
        cfg = _alembic_config()
        command.upgrade(cfg, "0013")
        engine = create_engine(get_settings().database_url)
        user_id, invite_id = uuid.uuid4(), uuid.uuid4()
        created = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (id, google_sub, email, digest_enabled, created_at) "
                    "VALUES (:id, 'sub-x', 'x@example.test', true, :t)"
                ),
                {"id": user_id, "t": created},
            )
            conn.execute(
                text(
                    "INSERT INTO invite_codes (id, code_hash, expires_at, used_at, "
                    "used_by_user_id, created_at) VALUES (:i, 'h', :t, :t, :u, :t)"
                ),
                {"i": invite_id, "u": user_id, "t": created},
            )
        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            done = conn.execute(
                text("SELECT setup_completed_at FROM users WHERE id = :id"), {"id": user_id}
            ).scalar_one()
            invite = conn.execute(
                text(
                    "SELECT used_at, used_by_user_id, claimed_by_user_id, revoked_at "
                    "FROM invite_codes WHERE id = :id"
                ),
                {"id": invite_id},
            ).one()
        assert done == created
        assert invite.used_at == created and invite.used_by_user_id == user_id
        assert invite.claimed_by_user_id is None and invite.revoked_at is None
        command.downgrade(cfg, "0013")
        command.upgrade(cfg, "head")
        engine.dispose()
