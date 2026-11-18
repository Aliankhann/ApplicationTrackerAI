"""Application reads. Every query is scoped by user_id."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Application, StatusEvent


def get_for_thread(
    session: Session, user_id: uuid.UUID, thread_id: uuid.UUID
) -> Application | None:
    stmt = select(Application).where(
        Application.user_id == user_id, Application.source_thread_id == thread_id
    )
    return session.scalars(stmt).one_or_none()


def get(session: Session, user_id: uuid.UUID, application_id: uuid.UUID) -> Application | None:
    stmt = select(Application).where(
        Application.user_id == user_id, Application.id == application_id
    )
    return session.scalars(stmt).one_or_none()


def list_events(
    session: Session, user_id: uuid.UUID, application_id: uuid.UUID
) -> list[StatusEvent]:
    """Timeline oldest first; empty when the application is not the user's."""
    stmt = (
        select(StatusEvent)
        .join(Application, Application.id == StatusEvent.application_id)
        .where(Application.user_id == user_id, StatusEvent.application_id == application_id)
        .order_by(StatusEvent.at, StatusEvent.seq)
    )
    return list(session.scalars(stmt).all())
