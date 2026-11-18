"""User lookups."""

import uuid

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User


def get(session: Session, user_id: uuid.UUID) -> User | None:
    return session.execute(select(User).where(User.id == user_id)).scalar_one_or_none()


def delete(session: Session, user_id: uuid.UUID) -> None:
    """Delete the user row; database cascades remove every dependent row."""
    session.execute(sa_delete(User).where(User.id == user_id))


def get_by_email(session: Session, email: str) -> User | None:
    return session.execute(select(User).where(User.email == email)).scalars().first()
