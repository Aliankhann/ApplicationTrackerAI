"""Digest queries (all scoped by user_id) and the digest_log claim protocol.

The unique (user_id, digest_date) key plus conditional UPDATEs make every transition atomic:
only the caller whose statement changed a row may proceed.
"""

import uuid
from datetime import date, datetime, timedelta
from typing import Any, NamedTuple, cast

from sqlalchemy import CursorResult, select
from sqlalchemy import update as sql_update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Application, DigestLog, EmailThread, FollowUpTask, StatusEvent, User
from app.services.classification import ApplicationStatus

SENDING = "sending"
SENT = "sent"
FAILED = "failed"
SKIPPED_EMPTY = "skipped_empty"
MAX_ATTEMPTS = 2
STALE_SENDING = timedelta(minutes=15)
_FOLLOWABLE = (ApplicationStatus.APPLIED, ApplicationStatus.ONLINE_ASSESSMENT)
_NOTABLE = (ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER, ApplicationStatus.REJECTED)


class AppRow(NamedTuple):
    application_id: uuid.UUID
    company: str | None
    status: ApplicationStatus


def enabled_users(session: Session) -> list[User]:
    stmt = select(User).where(User.digest_enabled.is_(True), User.disabled_at.is_(None))
    return list(session.scalars(stmt.order_by(User.created_at, User.id)))


def still_enabled(session: Session, user_id: uuid.UUID) -> bool:
    stmt = select(User.id).where(
        User.id == user_id, User.digest_enabled.is_(True), User.disabled_at.is_(None)
    )
    return session.scalars(stmt).first() is not None


def drafted_companies(session: Session, user_id: uuid.UUID) -> list[str | None]:
    stmt = (
        select(Application.company)
        .join(FollowUpTask, FollowUpTask.application_id == Application.id)
        .where(Application.user_id == user_id, FollowUpTask.state == "drafted")
        .order_by(FollowUpTask.drafted_at, FollowUpTask.id)
    )
    return list(session.scalars(stmt))


def _rows(session: Session, stmt: Any) -> list[AppRow]:
    return [AppRow(*row) for row in session.execute(stmt).all()]


def replies_since(
    session: Session, user_id: uuid.UUID, since: datetime, now: datetime
) -> list[AppRow]:
    stmt = (
        select(Application.id, Application.company, Application.status)
        .join(EmailThread, EmailThread.id == Application.source_thread_id)
        .where(
            Application.user_id == user_id,
            EmailThread.user_id == user_id,
            Application.needs_review.is_(False),
            EmailThread.last_sender_is_user.is_(False),
            Application.last_activity_at > since,
            Application.last_activity_at <= now,
        )
        .order_by(Application.last_activity_at, Application.id)
    )
    return _rows(session, stmt)


def notable_changes_since(
    session: Session, user_id: uuid.UUID, since: datetime, now: datetime
) -> list[AppRow]:
    """Moves to interview, offer or rejected that the classifier made (not manual edits)."""
    stmt = (
        select(Application.id, Application.company, StatusEvent.to_status)
        .join(StatusEvent, StatusEvent.application_id == Application.id)
        .where(
            Application.user_id == user_id,
            StatusEvent.at > since,
            StatusEvent.at <= now,
            StatusEvent.to_status.in_(_NOTABLE),
            StatusEvent.reason != "manual",
        )
        .order_by(StatusEvent.at, StatusEvent.seq)
    )
    return _rows(session, stmt)


def awaiting_reply(
    session: Session, user_id: uuid.UUID, newer_than: datetime, older_than: datetime
) -> list[AppRow]:
    stmt = (
        select(Application.id, Application.company, Application.status)
        .join(EmailThread, EmailThread.id == Application.source_thread_id)
        .where(
            Application.user_id == user_id,
            EmailThread.user_id == user_id,
            Application.status.in_(_FOLLOWABLE),
            Application.needs_review.is_(False),
            EmailThread.last_sender_is_user.is_(True),
            Application.last_activity_at > newer_than,
            Application.last_activity_at <= older_than,
        )
        .order_by(Application.last_activity_at, Application.id)
    )
    return _rows(session, stmt)


def last_sent_at(session: Session, user_id: uuid.UUID) -> datetime | None:
    stmt = (
        select(DigestLog.sent_at)
        .where(DigestLog.user_id == user_id, DigestLog.status == SENT)
        .order_by(DigestLog.sent_at.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def claim(session: Session, user_id: uuid.UUID, day: date, now: datetime) -> bool:
    """Insert the 'sending' row; True only for the caller that inserted it."""
    stmt = (
        insert(DigestLog)
        .values(
            id=uuid.uuid4(),
            user_id=user_id,
            digest_date=day,
            status=SENDING,
            attempts=1,
            claimed_at=now,
        )
        .on_conflict_do_nothing(index_elements=["user_id", "digest_date"])
        .returning(DigestLog.id)
    )
    return session.execute(stmt).first() is not None


def _update(session: Session, user_id: uuid.UUID, day: date, where: Any, **values: Any) -> bool:
    stmt = sql_update(DigestLog).where(
        DigestLog.user_id == user_id, DigestLog.digest_date == day, where
    )
    result = cast(CursorResult[Any], session.execute(stmt.values(**values)))
    return result.rowcount == 1


def reclaim_failed(session: Session, user_id: uuid.UUID, day: date, now: datetime) -> bool:
    """Take a failed row for its one retry; True only for the caller whose UPDATE won."""
    return _update(
        session,
        user_id,
        day,
        (DigestLog.status == FAILED) & (DigestLog.attempts < MAX_ATTEMPTS),
        status=SENDING,
        attempts=DigestLog.attempts + 1,
        claimed_at=now,
    )


def fail_stale(session: Session, user_id: uuid.UUID, day: date, now: datetime) -> bool:
    """A long-stale 'sending' row may or may not have been sent: close it with no retry.

    Tradeoff, deliberately in the safe direction: if the process died before sending, this user
    misses a digest that day; we never risk sending two.
    """
    return _update(
        session,
        user_id,
        day,
        (DigestLog.status == SENDING) & (DigestLog.claimed_at < now - STALE_SENDING),
        status=FAILED,
        attempts=MAX_ATTEMPTS,
    )


def finish(
    session: Session,
    user_id: uuid.UUID,
    day: date,
    status: str,
    sent_at: datetime | None = None,
) -> None:
    # Only a row still 'sending' may finish; a send that succeeded but whose row was already
    # closed as stale stays 'failed' (a missing record, never a duplicate send).
    _update(session, user_id, day, DigestLog.status == SENDING, status=status, sent_at=sent_at)
