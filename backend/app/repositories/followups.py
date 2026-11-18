"""Follow-up task queries. Tasks have no user_id, so every query joins applications by user_id."""

import uuid
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, and_, func, or_, select
from sqlalchemy import update as sql_update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import (
    Application,
    EmailThread,
    FollowUpTask,
    OAuthToken,
    SchedulerState,
    SyncState,
    TokenStatus,
)
from app.services.classification import ApplicationStatus

PENDING = "pending"
DRAFTING = "drafting"
DRAFTED = "drafted"
SENT = "sent"
SKIPPED = "skipped"
CANCELLED = "cancelled"
_FOLLOWABLE = (ApplicationStatus.APPLIED, ApplicationStatus.ONLINE_ASSESSMENT)


def plannable(session: Session, user_id: uuid.UUID) -> list[tuple[Application, EmailThread]]:
    """Applied / Online assessment applications, not paused, whose last message is the user's."""
    stmt = (
        select(Application, EmailThread)
        .join(EmailThread, EmailThread.id == Application.source_thread_id)
        .where(
            Application.user_id == user_id,
            EmailThread.user_id == user_id,
            Application.status.in_(_FOLLOWABLE),
            Application.followups_paused.is_(False),
            EmailThread.last_sender_is_user.is_(True),
        )
        .order_by(Application.created_at, Application.id)
    )
    return [(a, t) for a, t in session.execute(stmt).all()]


def insert_if_absent(
    session: Session,
    application_id: uuid.UUID,
    sequence_id: uuid.UUID,
    step_index: int,
    due_at: datetime,
    created_at: datetime,
    *,
    state: str = PENDING,
    cancel_reason: str | None = None,
) -> bool:
    stmt = (
        insert(FollowUpTask)
        .values(
            id=uuid.uuid4(),
            application_id=application_id,
            sequence_id=sequence_id,
            step_index=step_index,
            due_at=due_at,
            state=state,
            cancel_reason=cancel_reason,
            created_at=created_at,
        )
        .on_conflict_do_nothing(constraint="uq_follow_up_tasks_application_id_step_index")
        .returning(FollowUpTask.id)
    )
    return session.execute(stmt).first() is not None


def due_pending(session: Session, user_id: uuid.UUID, now: datetime) -> list[FollowUpTask]:
    """Locks the rows; other workers skip them."""
    stmt = (
        select(FollowUpTask)
        .join(Application, FollowUpTask.application_id == Application.id)
        .where(Application.user_id == user_id, FollowUpTask.state == PENDING)
        .where(FollowUpTask.due_at <= now)
        .order_by(FollowUpTask.due_at, FollowUpTask.id)
        .with_for_update(skip_locked=True, of=FollowUpTask)
    )
    return list(session.scalars(stmt).all())


def in_state(session: Session, user_id: uuid.UUID, state: str) -> list[FollowUpTask]:
    stmt = (
        select(FollowUpTask)
        .join(Application, FollowUpTask.application_id == Application.id)
        .where(Application.user_id == user_id, FollowUpTask.state == state)
        .order_by(FollowUpTask.due_at, FollowUpTask.id)
    )
    return list(session.scalars(stmt).all())


def for_application(
    session: Session, user_id: uuid.UUID, application_id: uuid.UUID
) -> list[FollowUpTask]:
    stmt = (
        select(FollowUpTask)
        .join(Application, FollowUpTask.application_id == Application.id)
        .where(Application.user_id == user_id, FollowUpTask.application_id == application_id)
        .order_by(FollowUpTask.step_index)
    )
    return list(session.scalars(stmt).all())


def cancel_pending(
    session: Session,
    user_id: uuid.UUID,
    reason: str,
    *,
    application_id: uuid.UUID | None = None,
    from_step: int = 0,
) -> int:
    """Cancel pending tasks of the user (optionally one application, from a step onward)."""
    owned = select(Application.id).where(Application.user_id == user_id)
    stmt = (
        sql_update(FollowUpTask)
        .where(
            FollowUpTask.application_id.in_(owned),
            FollowUpTask.state == PENDING,
            FollowUpTask.step_index >= from_step,
        )
        .values(state=CANCELLED, cancel_reason=reason)
        .execution_options(synchronize_session="fetch")
    )
    if application_id is not None:
        stmt = stmt.where(FollowUpTask.application_id == application_id)
    result = cast(CursorResult[Any], session.execute(stmt))
    return result.rowcount


def count_drafted_between(
    session: Session, user_id: uuid.UUID, start: datetime, end: datetime
) -> int:
    stmt = (
        select(func.count())
        .select_from(FollowUpTask)
        .join(Application, FollowUpTask.application_id == Application.id)
        .where(
            Application.user_id == user_id,
            or_(
                and_(FollowUpTask.drafted_at >= start, FollowUpTask.drafted_at < end),
                and_(
                    FollowUpTask.state == DRAFTING,
                    FollowUpTask.claimed_at >= start,
                    FollowUpTask.claimed_at < end,
                ),
            ),
        )
    )
    return session.scalar(stmt) or 0


def has_drafted(session: Session, user_id: uuid.UUID, application_id: uuid.UUID) -> bool:
    """True while an earlier draft for the application waits for the user."""
    return any(t.state == DRAFTED for t in for_application(session, user_id, application_id))


def count_attempts(session: Session, user_id: uuid.UUID, application_id: uuid.UUID) -> int:
    """Drafts created for the application, whether still drafted or since sent."""
    stmt = (
        select(func.count())
        .select_from(FollowUpTask)
        .join(Application, FollowUpTask.application_id == Application.id)
        .where(
            Application.user_id == user_id,
            FollowUpTask.application_id == application_id,
            FollowUpTask.drafted_at.is_not(None),
        )
    )
    return session.scalar(stmt) or 0


def latest_sent_at(
    session: Session, user_id: uuid.UUID, application_id: uuid.UUID
) -> datetime | None:
    stmt = (
        select(func.max(FollowUpTask.sent_at))
        .join(Application, FollowUpTask.application_id == Application.id)
        .where(Application.user_id == user_id, FollowUpTask.application_id == application_id)
    )
    return session.scalar(stmt)


def gmail_revoked(session: Session, user_id: uuid.UUID) -> bool:
    token = session.scalar(select(OAuthToken.status).where(OAuthToken.user_id == user_id))
    sync = session.scalar(select(SyncState.status).where(SyncState.user_id == user_id))
    return token == TokenStatus.REVOKED or sync == "revoked"


def thread_for(session: Session, user_id: uuid.UUID, thread_id: uuid.UUID) -> EmailThread | None:
    stmt = select(EmailThread).where(EmailThread.user_id == user_id, EmailThread.id == thread_id)
    return session.scalars(stmt).one_or_none()


def _rowcount(session: Session, stmt: Any) -> int:
    return cast(CursorResult[Any], session.execute(stmt)).rowcount


def claim_lease(session: Session, user_id: uuid.UUID, now: datetime, ttl: timedelta) -> bool:
    """Atomically take the user's scheduler lease; False when a live run holds it."""
    session.execute(insert(SchedulerState).values(user_id=user_id).on_conflict_do_nothing())
    stmt = (
        sql_update(SchedulerState)
        .where(
            SchedulerState.user_id == user_id,
            or_(SchedulerState.lease_expires_at.is_(None), SchedulerState.lease_expires_at < now),
        )
        .values(lease_expires_at=now + ttl, started_at=now)
    )
    return _rowcount(session, stmt) == 1


def renew_lease(session: Session, user_id: uuid.UUID, expires_at: datetime) -> None:
    session.execute(
        sql_update(SchedulerState)
        .where(SchedulerState.user_id == user_id)
        .values(lease_expires_at=expires_at)
    )


def release_lease(session: Session, user_id: uuid.UUID) -> None:
    session.execute(
        sql_update(SchedulerState)
        .where(SchedulerState.user_id == user_id)
        .values(lease_expires_at=None, started_at=None)
    )


def claim_task(session: Session, task_id: uuid.UUID, now: datetime) -> bool:
    """pending -> drafting, atomically; False when another worker already claimed it."""
    stmt = (
        sql_update(FollowUpTask)
        .where(FollowUpTask.id == task_id, FollowUpTask.state == PENDING)
        .values(state=DRAFTING, claimed_at=now)
        .execution_options(synchronize_session="fetch")
    )
    return _rowcount(session, stmt) == 1


def stale_drafting(session: Session, user_id: uuid.UUID, before: datetime) -> list[FollowUpTask]:
    stmt = (
        select(FollowUpTask)
        .join(Application, FollowUpTask.application_id == Application.id)
        .where(
            Application.user_id == user_id,
            FollowUpTask.state == DRAFTING,
            FollowUpTask.claimed_at < before,
        )
        .order_by(FollowUpTask.due_at, FollowUpTask.id)
    )
    return list(session.scalars(stmt).all())


def get_owned(session: Session, user_id: uuid.UUID, task_id: uuid.UUID) -> FollowUpTask | None:
    stmt = (
        select(FollowUpTask)
        .join(Application, FollowUpTask.application_id == Application.id)
        .where(Application.user_id == user_id, FollowUpTask.id == task_id)
    )
    return session.scalars(stmt).one_or_none()


def list_queue(
    session: Session, user_id: uuid.UUID, states: tuple[str, ...]
) -> list[tuple[FollowUpTask, Application]]:
    stmt = (
        select(FollowUpTask, Application)
        .join(Application, FollowUpTask.application_id == Application.id)
        .where(Application.user_id == user_id, FollowUpTask.state.in_(states))
        .order_by(FollowUpTask.due_at, FollowUpTask.id)
    )
    return [(t, a) for t, a in session.execute(stmt).all()]


def skip_pending(session: Session, user_id: uuid.UUID, task_id: uuid.UUID) -> bool:
    """pending -> skipped, atomically against the scheduler's claim; False if not pending."""
    owned = select(Application.id).where(Application.user_id == user_id)
    stmt = (
        sql_update(FollowUpTask)
        .where(
            FollowUpTask.id == task_id,
            FollowUpTask.application_id.in_(owned),
            FollowUpTask.state == PENDING,
        )
        .values(state=SKIPPED, cancel_reason="user_skipped")
        .execution_options(synchronize_session="fetch")
    )
    return _rowcount(session, stmt) == 1


def delay_pending(session: Session, user_id: uuid.UUID, task_id: uuid.UUID, days: int) -> bool:
    """Push a pending task's due_at later; False if it is no longer pending."""
    owned = select(Application.id).where(Application.user_id == user_id)
    stmt = (
        sql_update(FollowUpTask)
        .where(
            FollowUpTask.id == task_id,
            FollowUpTask.application_id.in_(owned),
            FollowUpTask.state == PENDING,
        )
        .values(due_at=FollowUpTask.due_at + timedelta(days=days))
        .execution_options(synchronize_session="fetch")
    )
    return _rowcount(session, stmt) == 1


def application_of(
    session: Session, user_id: uuid.UUID, application_id: uuid.UUID
) -> Application | None:
    stmt = select(Application).where(
        Application.user_id == user_id, Application.id == application_id
    )
    return session.scalars(stmt).one_or_none()
