"""US-16 audit log, US-35 disconnect Gmail, US-80 delete my data."""

import base64
import os
import uuid
from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.api.deps import get_email_sender, get_token_revoker
from app.config import get_settings
from app.db import Base
from app.models import (
    Application,
    AuditAction,
    AuditLog,
    DigestLog,
    EmailThread,
    FollowUpTask,
    InviteCode,
    OAuthToken,
    SchedulerState,
    SyncState,
    SyncStatus,
    User,
    UserSession,
)
from app.providers.email import FakeEmailSender
from app.providers.google.revoke import FakeTokenRevoker, RevokeResult
from app.repositories import audit as audit_repo
from app.repositories import oauth_tokens
from app.security.crypto import get_keyring
from app.services import sync
from app.services.sync import SyncUserGone
from tests.test_applications_api import login
from tests.test_isolation import GLOBAL_TABLES, World, build_world, covered_tables, snapshot
from tests.test_sessions import T0, Env, env  # noqa: F401
from tests.test_sync import CLASSIFIER, NOW, fake

REFRESH_TOKEN = "1//synthetic-refresh-token"  # noqa: S105
CONFIRM = {"confirm": "DELETE"}


@pytest.fixture(autouse=True)
def _keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEYS", f"1:{key}")
    monkeypatch.setenv("TOKEN_ENCRYPTION_CURRENT_VERSION", "1")


class Wired:
    def __init__(self, env: Env, user: User) -> None:  # noqa: F811
        self.revoker = FakeTokenRevoker()
        self.sender = FakeEmailSender()
        self.client = login(env, user)
        app = self.client.app
        assert isinstance(app, FastAPI)
        app.dependency_overrides[get_token_revoker] = lambda: self.revoker
        app.dependency_overrides[get_email_sender] = lambda: self.sender


def connected(env: Env, tag: str = "Alpha") -> tuple[World, Wired]:  # noqa: F811
    """A user with a live token and one of every owned row."""
    world = build_world(env, tag)
    oauth_tokens.save_refresh_token(
        env.db, world.user.id, REFRESH_TOKEN, "gmail.readonly", get_keyring()
    )
    env.db.add(SyncState(user_id=world.user.id, history_id="42", initial_sync_done=True))
    env.db.flush()
    return world, Wired(env, world.user)


def count(db: Session, model: type[Any], **where: Any) -> int:
    stmt = select(func.count()).select_from(model)
    for key, value in where.items():
        stmt = stmt.where(getattr(model, key) == value)
    return db.scalar(stmt) or 0


# ---------- US-16 audit log ----------


def test_us16_logout_writes_exactly_one_row_with_only_user_action_and_time(env: Env) -> None:  # noqa: F811
    user = env.user()
    client = login(env, user)
    assert client.post("/auth/logout").status_code == 204
    rows = env.db.scalars(select(AuditLog)).all()
    assert [(r.user_id, r.action, r.at) for r in rows] == [(user.id, "logout", T0)]
    assert {c.name for c in AuditLog.__table__.columns} == {"id", "user_id", "action", "at"}


def test_us16_audit_user_id_has_no_foreign_key_and_actions_are_checked() -> None:
    assert not AuditLog.__table__.foreign_keys
    assert {a.value for a in AuditAction} == {
        "login",
        "logout",
        "gmail_connected",
        "gmail_disconnected",
        "account_deleted",
        "followups_enabled",
        "data_exported",
    }


def test_us16_record_helper_writes_any_action(env: Env) -> None:  # noqa: F811
    user = env.user()
    for action in AuditAction:
        audit_repo.record(env.db, user.id, action, T0)
    assert count(env.db, AuditLog, user_id=user.id) == len(AuditAction)


def test_us16_purge_audit_deletes_only_entries_older_than_retention(env: Env) -> None:  # noqa: F811
    user = env.user()
    audit_repo.record(env.db, user.id, AuditAction.LOGIN, T0 - timedelta(days=366))
    audit_repo.record(env.db, user.id, AuditAction.LOGIN, T0 - timedelta(days=364))
    assert audit_repo.purge_audit(env.db, T0) == 1
    assert count(env.db, AuditLog) == 1


# ---------- US-35 disconnect ----------


def test_us35_disconnect_revokes_once_and_deletes_threads_token_and_resets_sync(
    env: Env,  # noqa: F811
) -> None:
    world, w = connected(env)
    response = w.client.post("/gmail/disconnect")
    assert response.status_code == 200
    assert response.json() == {"revoked_at_google": True}
    assert w.revoker.calls == [REFRESH_TOKEN]
    uid = world.user.id
    assert count(env.db, EmailThread, user_id=uid) == 0
    assert count(env.db, OAuthToken, user_id=uid) == 0
    state = env.db.scalars(select(SyncState).where(SyncState.user_id == uid)).one()
    env.db.refresh(state)
    assert (state.history_id, state.initial_sync_done, state.status) == (None, False, "idle")


def test_us35_applications_survive_without_their_thread_and_open_tasks_are_cancelled(
    env: Env,  # noqa: F811
) -> None:
    world, w = connected(env)
    w.client.post("/gmail/disconnect")
    app_row = env.db.get(Application, world.application.id)
    assert app_row is not None
    env.db.refresh(app_row)
    assert app_row.company == world.company and app_row.source_thread_id is None
    task = env.db.get(FollowUpTask, world.task.id)
    assert task is not None
    env.db.refresh(task)
    assert (task.state, task.cancel_reason) == ("cancelled", "gmail_disconnected")


def test_us35_disconnect_writes_one_audit_row(env: Env) -> None:  # noqa: F811
    world, w = connected(env)
    w.client.post("/gmail/disconnect")
    w.client.post("/gmail/disconnect")
    rows = env.db.scalars(select(AuditLog).where(AuditLog.user_id == world.user.id)).all()
    assert [r.action for r in rows] == ["gmail_disconnected"]


def test_us35_already_invalid_token_counts_as_revoked(env: Env) -> None:  # noqa: F811
    _, w = connected(env)
    w.revoker.result = RevokeResult.ALREADY_INVALID
    assert w.client.post("/gmail/disconnect").json() == {"revoked_at_google": True}


def test_us35_google_failure_still_cleans_up_locally_and_reports_it(env: Env) -> None:  # noqa: F811
    world, w = connected(env)
    w.revoker.result = RevokeResult.FAILED
    response = w.client.post("/gmail/disconnect")
    assert response.status_code == 200
    assert response.json() == {"revoked_at_google": False}
    assert count(env.db, EmailThread, user_id=world.user.id) == 0
    assert count(env.db, OAuthToken, user_id=world.user.id) == 0


def test_us35_disconnect_without_a_token_is_an_idempotent_200(env: Env) -> None:  # noqa: F811
    user = env.user()
    w = Wired(env, user)
    response = w.client.post("/gmail/disconnect")
    assert (response.status_code, response.json()) == (200, {"revoked_at_google": None})
    assert w.revoker.calls == []
    assert count(env.db, AuditLog) == 0


def test_us35_live_sync_lease_gives_409_and_changes_nothing(env: Env) -> None:  # noqa: F811
    world, w = connected(env)
    state = env.db.get(SyncState, world.user.id)
    assert state is not None
    state.status = SyncStatus.RUNNING.value
    state.lease_expires_at = T0 + timedelta(minutes=5)
    env.db.flush()
    response = w.client.post("/gmail/disconnect")
    assert (response.status_code, response.json()) == (409, {"detail": "sync_in_progress"})
    assert w.revoker.calls == []
    assert count(env.db, EmailThread, user_id=world.user.id) == 1
    state.lease_expires_at = T0 - timedelta(minutes=1)  # a crashed sync's expired lease
    env.db.flush()
    assert w.client.post("/gmail/disconnect").status_code == 200


def test_us35_unconfigured_revoker_gives_503_and_changes_nothing(env: Env) -> None:  # noqa: F811
    world, w = connected(env)
    app = w.client.app
    assert isinstance(app, FastAPI)
    del app.dependency_overrides[get_token_revoker]
    response = w.client.post("/gmail/disconnect")
    assert (response.status_code, response.json()) == (503, {"detail": "revocation_unavailable"})
    assert count(env.db, OAuthToken, user_id=world.user.id) == 1
    assert count(env.db, EmailThread, user_id=world.user.id) == 1


def test_us35_disconnect_by_user_b_leaves_user_a_untouched(env: Env) -> None:  # noqa: F811
    a, _ = connected(env, "Alpha")
    _, b = connected(env, "Bravo")
    before = snapshot(env.db, a)
    assert b.client.post("/gmail/disconnect").status_code == 200
    assert snapshot(env.db, a) == before


# ---------- US-80 delete my data ----------


def seed_every_table(env: Env, world: World, w: Wired) -> uuid.UUID:  # noqa: F811
    """Add the rows `connected` does not: lease, invite code, audit, digest log, second session."""
    uid = world.user.id
    env.db.add(SchedulerState(user_id=uid, lease_expires_at=T0 + timedelta(minutes=5)))
    invite = InviteCode(code_hash=uuid.uuid4().hex, expires_at=T0, used_by_user_id=uid, used_at=T0)
    env.db.add(invite)
    audit_repo.record(env.db, uid, AuditAction.LOGIN, T0)
    env.db.add(DigestLog(user_id=uid, digest_date=T0.date(), status="sent", claimed_at=T0))
    env.login(world.user)
    env.db.flush()
    return invite.id


def test_us80_delete_leaves_zero_rows_in_every_user_table(env: Env) -> None:  # noqa: F811
    world, w = connected(env)
    other = connected(env, "Bravo")[0]
    invite_id = seed_every_table(env, world, w)
    others_before = snapshot(env.db, other)
    tables = covered_tables()
    for name in tables:  # fails when a new table is not seeded here
        assert snapshot(env.db, world)[name], f"seed a row in {name}"
    assert not set(Base.metadata.tables) - {"users"} - set(tables) - GLOBAL_TABLES

    response = w.client.request("DELETE", "/me", json=CONFIRM)

    assert response.status_code == 200
    assert response.json() == {"deleted": True, "revoked_at_google": True}
    after = snapshot(env.db, world)
    assert after.pop("users") == []
    assert {name: rows for name, rows in after.items() if rows} == {}
    assert snapshot(env.db, other) == others_before
    invite = env.db.get(InviteCode, invite_id)
    assert invite is not None
    env.db.refresh(invite)
    assert invite.used_by_user_id is None and invite.used_at == T0  # slot still counts


def test_us80_revokes_token_clears_cookies_ends_session_and_sends_confirmation(
    env: Env,  # noqa: F811
) -> None:
    world, w = connected(env)
    response = w.client.request("DELETE", "/me", json=CONFIRM)
    assert w.revoker.calls == [REFRESH_TOKEN]
    cleared = " ".join(response.headers.get_list("set-cookie")).lower()
    assert "tracker_session=" in cleared and "max-age=0" in cleared
    assert w.sender.deletion_confirmations == ["u@example.test"]
    w.client.cookies.clear()
    assert count(env.db, UserSession, user_id=world.user.id) == 0
    assert w.client.get("/me").status_code == 401


def test_us80_audit_rows_are_replaced_by_one_anonymous_account_deleted_entry(
    env: Env,  # noqa: F811
) -> None:
    world, w = connected(env)
    audit_repo.record(env.db, world.user.id, AuditAction.LOGIN, T0)
    w.client.request("DELETE", "/me", json=CONFIRM)
    rows = env.db.scalars(select(AuditLog)).all()
    assert [(r.user_id, r.action) for r in rows] == [(None, "account_deleted")]


@pytest.mark.parametrize(
    "body", [None, {}, {"confirm": "delete"}, {"confirm": "DELETE "}, {"confirm": "DELETE", "x": 1}]
)
def test_us80_wrong_or_missing_confirmation_is_422_and_deletes_nothing(
    env: Env,  # noqa: F811
    body: dict[str, object] | None,
) -> None:
    world, w = connected(env)
    response = (
        w.client.request("DELETE", "/me", json=body) if body is not None else w.client.delete("/me")
    )
    assert response.status_code == 422
    assert env.db.get(User, world.user.id) is not None
    assert w.revoker.calls == []


@pytest.mark.parametrize("configured", [True, False])
def test_us80_google_failure_never_blocks_deletion(env: Env, configured: bool) -> None:  # noqa: F811
    world, w = connected(env)
    w.revoker.result = RevokeResult.FAILED
    if not configured:
        app = w.client.app
        assert isinstance(app, FastAPI)
        del app.dependency_overrides[get_token_revoker]
    response = w.client.request("DELETE", "/me", json=CONFIRM)
    assert (response.status_code, response.json()) == (
        200,
        {"deleted": True, "revoked_at_google": False},
    )
    assert env.db.get(User, world.user.id) is None


def test_us80_user_without_a_token_reports_null_revocation(env: Env) -> None:  # noqa: F811
    w = Wired(env, env.user())
    response = w.client.request("DELETE", "/me", json=CONFIRM)
    assert response.json() == {"deleted": True, "revoked_at_google": None}


def test_us80_confirmation_email_failure_does_not_fail_the_deletion(env: Env) -> None:  # noqa: F811
    world, w = connected(env)

    class Broken:
        def send_deletion_confirmation(self, to_address: str) -> None:
            raise RuntimeError("smtp down")

    app = w.client.app
    assert isinstance(app, FastAPI)
    app.dependency_overrides[get_email_sender] = Broken
    assert w.client.request("DELETE", "/me", json=CONFIRM).status_code == 200
    assert env.db.get(User, world.user.id) is None


def test_us80_user_b_deleting_themselves_leaves_user_a_untouched(env: Env) -> None:  # noqa: F811
    a, _ = connected(env, "Alpha")
    _, b = connected(env, "Bravo")
    before = snapshot(env.db, a)
    assert b.client.request("DELETE", "/me", json=CONFIRM).status_code == 200
    assert snapshot(env.db, a) == before


# ---------- deletion racing background work ----------


@pytest.fixture
def committed_user() -> Any:
    """A user in a real committed database (not the rolled-back test transaction)."""
    engine = create_engine(get_settings().database_url)
    with Session(engine) as s:
        user = User(google_sub=uuid.uuid4().hex, email="race@example.test")
        s.add(user)
        s.commit()
        uid = user.id
    yield engine, uid
    with Session(engine) as s:
        s.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
        s.commit()
    engine.dispose()


def total_rows_for(engine: Any, uid: uuid.UUID) -> int:
    total = 0
    with Session(engine) as s:
        for table in Base.metadata.tables.values():
            if table.name == "users":
                total += (
                    s.scalar(select(func.count()).select_from(table).where(table.c.id == uid)) or 0
                )
            elif "user_id" in table.c:
                total += (
                    s.scalar(select(func.count()).select_from(table).where(table.c.user_id == uid))
                    or 0
                )
    return total


def test_us80_user_deleted_between_two_sync_batches_leaves_zero_rows(
    committed_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, uid = committed_user
    monkeypatch.setattr(sync, "BATCH_SIZE", 1)
    commits: list[int] = []

    with Session(engine) as session:

        def commit_then_delete_after_first_batch() -> None:
            session.commit()
            commits.append(1)
            if len(commits) == 2:  # claim, then the first batch checkpoint
                with Session(engine) as other:
                    other.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
                    other.commit()

        result = sync.run_sync(
            session, uid, fake(), CLASSIFIER, NOW, commit=commit_then_delete_after_first_batch
        )
    assert isinstance(result, SyncUserGone)
    assert len(commits) >= 2
    assert total_rows_for(engine, uid) == 0


def test_us80_sync_for_an_already_deleted_user_stops_cleanly_and_writes_nothing(
    committed_user: Any,
) -> None:
    engine, uid = committed_user
    with Session(engine) as s:
        s.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
        s.commit()
    with Session(engine) as s:
        assert isinstance(sync.run_sync(s, uid, fake(), CLASSIFIER, NOW), SyncUserGone)
    assert total_rows_for(engine, uid) == 0


def test_us80_scheduler_run_stops_cleanly_when_the_user_vanishes_mid_run(
    committed_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import scheduler

    engine, uid = committed_user

    def vanish(run: Any) -> None:
        with Session(engine) as other:
            other.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
            other.commit()
        raise RuntimeError("row gone")

    monkeypatch.setattr(scheduler, "_resolve_stale_claims", vanish)
    with Session(engine) as s:
        result = scheduler.run_due(s, uid, fake(), NOW)
    assert not result.already_running
    assert total_rows_for(engine, uid) == 0
