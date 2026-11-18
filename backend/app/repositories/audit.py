"""Audit log: user id, action, and time only. Never IPs, user agents, emails, or content."""

import uuid
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, delete
from sqlalchemy.orm import Session

from app.models import AuditAction, AuditLog

RETENTION_DAYS = 365


def record(session: Session, user_id: uuid.UUID | None, action: AuditAction, now: datetime) -> None:
    """Add one entry in the caller's transaction. `user_id` is None for anonymous entries."""
    session.add(AuditLog(user_id=user_id, action=action.value, at=now))
    session.flush()


def delete_for_user(session: Session, user_id: uuid.UUID) -> None:
    session.execute(delete(AuditLog).where(AuditLog.user_id == user_id))


def purge_audit(session: Session, now: datetime, days: int = RETENTION_DAYS) -> int:
    """Delete entries older than `days`; returns how many."""
    stmt = delete(AuditLog).where(AuditLog.at < now - timedelta(days=days))
    return cast(CursorResult[Any], session.execute(stmt)).rowcount
