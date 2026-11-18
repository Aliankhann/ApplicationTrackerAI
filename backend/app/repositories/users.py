"""User lookups."""

import uuid

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
