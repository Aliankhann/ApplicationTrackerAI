"""Sync state queries used when disconnecting Gmail."""

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import SyncState, SyncStatus


def lease_held(session: Session, user_id: uuid.UUID, now: datetime) -> bool:
    """True while a sync holds an unexpired lease. Locks the row so no sync can claim meanwhile."""
    state = session.scalars(
        select(SyncState).where(SyncState.user_id == user_id).with_for_update()
    ).one_or_none()
    return (
        state is not None
        and state.status == SyncStatus.RUNNING.value
        and state.lease_expires_at is not None
        and state.lease_expires_at >= now
    )


def reset(session: Session, user_id: uuid.UUID) -> None:
    """Back to a fresh, idle state so a later connect does an initial sync."""
    stmt = (
        update(SyncState)
        .where(SyncState.user_id == user_id)
        .values(
            history_id=None,
            last_synced_at=None,
            initial_sync_done=False,
            status=SyncStatus.IDLE.value,
            last_error=None,
            started_at=None,
            lease_expires_at=None,
        )
    )
    session.execute(stmt)


def get(session: Session, user_id: uuid.UUID) -> SyncState | None:
    return session.get(SyncState, user_id)


def lease_active(state: SyncState | None, now: datetime) -> bool:
    """True while a sync holds an unexpired lease (no row lock)."""
    return (
        state is not None
        and state.status == SyncStatus.RUNNING.value
        and state.lease_expires_at is not None
        and state.lease_expires_at >= now
    )


def clear_revoked(session: Session, user_id: uuid.UUID) -> None:
    """A fresh connect lifts the revoked flag so syncing and follow-ups can resume."""
    stmt = (
        update(SyncState)
        .where(SyncState.user_id == user_id, SyncState.status == SyncStatus.REVOKED.value)
        .values(status=SyncStatus.IDLE.value, last_error=None)
    )
    session.execute(stmt)
