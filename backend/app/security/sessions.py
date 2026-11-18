"""Server-side sessions. The raw cookie token is never stored or logged, only its SHA-256.

Sign-in (US-11) must ALWAYS call `create_session`, even when the browser already holds a
session cookie, so a pre-login session id is never promoted (no session fixation).
"""

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import User, UserSession

SLIDE_INTERVAL = timedelta(minutes=5)
MAX_ACTIVE_SESSIONS = 10
PURGE_AFTER = timedelta(days=7)


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def derive_csrf_token(row: UserSession, settings: Settings) -> str:
    key = settings.session_secret.get_secret_value().encode()
    return hmac.new(key, f"{row.id}{row.csrf_secret}".encode(), hashlib.sha256).hexdigest()


def create_session(
    session: Session,
    user_id: uuid.UUID,
    now: datetime,
    settings: Settings,
    user_agent: str | None = None,
) -> tuple[str, str, UserSession]:
    """Create a session; returns (raw_token, csrf_token, row). Caller commits."""
    raw_token = secrets.token_urlsafe(32)
    row = UserSession(
        id=uuid.uuid4(),
        user_id=user_id,
        token_hash=hash_token(raw_token),
        csrf_secret=secrets.token_hex(32),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(days=settings.session_absolute_days),
        idle_expires_at=now + timedelta(hours=settings.session_idle_hours),
        user_agent_hash=hash_token(user_agent) if user_agent else None,
    )
    session.add(row)
    session.flush()
    _cap_active_sessions(session, user_id, now)
    return raw_token, derive_csrf_token(row, settings), row


def resolve(
    session: Session, raw_token: str, now: datetime, settings: Settings
) -> UserSession | None:
    """Return the live session for a raw token, sliding the idle window at most every 5 min."""
    # The lookup is by hash of a high-entropy token, so no timing signal about the token leaks.
    row = session.execute(
        select(UserSession)
        .join(User, User.id == UserSession.user_id)
        .where(UserSession.token_hash == hash_token(raw_token), User.disabled_at.is_(None))
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return None
    if row.expires_at <= now or row.idle_expires_at <= now:
        return None
    if now - row.last_seen_at >= SLIDE_INTERVAL:
        row.last_seen_at = now
        row.idle_expires_at = min(
            now + timedelta(hours=settings.session_idle_hours), row.expires_at
        )
        session.flush()
    return row


def revoke(session: Session, session_id: uuid.UUID, now: datetime) -> None:
    session.execute(
        update(UserSession)
        .where(UserSession.id == session_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )


def revoke_all_for_user(session: Session, user_id: uuid.UUID, now: datetime) -> None:
    session.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )


def _cap_active_sessions(session: Session, user_id: uuid.UUID, now: datetime) -> None:
    """Keep the newest MAX_ACTIVE_SESSIONS active sessions; revoke the older ones."""
    stale = (
        select(UserSession.id)
        .where(
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
        .order_by(UserSession.created_at.desc(), UserSession.id)
        .offset(MAX_ACTIVE_SESSIONS)
    )
    session.execute(
        update(UserSession)
        .where(UserSession.id.in_(stale))
        .values(revoked_at=now)
        .execution_options(synchronize_session="fetch")
    )


def purge_expired(session: Session, now: datetime) -> int:
    """Delete sessions that expired or were revoked more than 7 days ago."""
    cutoff = now - PURGE_AFTER
    result = session.execute(
        delete(UserSession).where(
            or_(UserSession.expires_at < cutoff, UserSession.revoked_at < cutoff)
        )
    )
    return int(result.rowcount)  # type: ignore[attr-defined]
