"""User lookups."""

import uuid
from datetime import datetime

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from app.models import User


def get(session: Session, user_id: uuid.UUID) -> User | None:
    return session.execute(select(User).where(User.id == user_id)).scalar_one_or_none()


def delete(session: Session, user_id: uuid.UUID) -> None:
    """Delete the user row; database cascades remove every dependent row."""
    session.execute(sa_delete(User).where(User.id == user_id))


def get_by_email(session: Session, email: str) -> User | None:
    return session.execute(select(User).where(User.email == email)).scalars().first()


def set_digest_enabled(session: Session, user_id: uuid.UUID, enabled: bool) -> None:
    """Idempotent; a missing user (deleted account) is a no-op."""
    session.execute(sa_update(User).where(User.id == user_id).values(digest_enabled=enabled))


def get_by_google_sub(session: Session, google_sub: str) -> User | None:
    return session.execute(select(User).where(User.google_sub == google_sub)).scalar_one_or_none()


def create(
    session: Session, google_sub: str, email: str, setup_completed_at: datetime | None
) -> User:
    """`setup_completed_at=None` creates a pending user (invited, Gmail not connected yet)."""
    user = User(google_sub=google_sub, email=email, setup_completed_at=setup_completed_at)
    session.add(user)
    session.flush()
    return user
