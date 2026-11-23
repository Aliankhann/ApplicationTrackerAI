"""Sync state queries used when disconnecting Gmail."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.models import OAuthToken, SyncState, SyncStatus, TokenStatus, User


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
            pending_history_id=None,
            list_page_token=None,
            last_synced_at=None,
            initial_sync_done=False,
            status=SyncStatus.IDLE.value,
            last_error=None,
            consecutive_rate_limits=0,
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


def due_for_sync(session: Session, now: datetime, min_gap: timedelta) -> list[uuid.UUID]:
    """Enabled users with a live token that were not synced within `min_gap`, never-synced and
    oldest first (so users a budget-limited run did not reach go first next time)."""
    stmt = (
        select(OAuthToken.user_id)
        .join(User, User.id == OAuthToken.user_id)
        .outerjoin(SyncState, SyncState.user_id == OAuthToken.user_id)
        .where(
            OAuthToken.status == TokenStatus.ACTIVE,
            User.disabled_at.is_(None),
            or_(
                SyncState.last_synced_at.is_(None),
                SyncState.last_synced_at < now - min_gap,
                SyncState.status == SyncStatus.PAUSED.value,  # unfinished: keep going
            ),
        )
        .order_by(SyncState.last_synced_at.asc().nulls_first(), OAuthToken.user_id)
    )
    return list(session.scalars(stmt))
