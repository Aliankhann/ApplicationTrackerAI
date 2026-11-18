"""Application reads. Every query is scoped by user_id."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import (
    ColumnElement,
    Select,
    String,
    and_,
    case,
    cast,
    func,
    not_,
    select,
    tuple_,
)
from sqlalchemy.orm import Session

from app.models import Application, Classification, EmailThread, StatusEvent
from app.services.classification import ApplicationStatus


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


GHOSTABLE = (ApplicationStatus.APPLIED, ApplicationStatus.ONLINE_ASSESSMENT)
GHOSTED = "ghosted"
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
SortField = Literal["last_activity", "applied_at"]


@dataclass(frozen=True)
class ApplicationView:
    application: Application
    display_status: str
    needs_review: bool
    subject: str | None
    snippet: str | None


@dataclass(frozen=True)
class PageCursor:
    key: datetime
    id: uuid.UUID


def sort_key(application: Application, sort: SortField) -> datetime:
    if sort == "last_activity":
        return application.last_activity_at
    return application.applied_at or EPOCH


def _key_column(sort: SortField) -> Any:
    if sort == "last_activity":
        return Application.last_activity_at
    return func.coalesce(Application.applied_at, EPOCH)


def _ghosted(cutoff: datetime) -> ColumnElement[bool]:
    return and_(
        Application.status.in_(GHOSTABLE),
        EmailThread.last_sender_is_user.is_(True),
        Application.last_activity_at < cutoff,
    )


def _view_select(cutoff: datetime) -> Select[Any]:
    latest_review = (
        select(Classification.needs_review)
        .where(Classification.thread_id == Application.source_thread_id)
        .order_by(Classification.seq.desc())
        .limit(1)
        .scalar_subquery()
    )
    display = case((_ghosted(cutoff), GHOSTED), else_=cast(Application.status, String)).label(
        "display_status"
    )
    return select(
        Application,
        display,
        func.coalesce(latest_review, False).label("needs_review"),
        EmailThread.subject,
        EmailThread.snippet,
    ).outerjoin(
        EmailThread,
        and_(
            EmailThread.id == Application.source_thread_id,
            EmailThread.user_id == Application.user_id,
        ),
    )


def _view(row: Any) -> ApplicationView:
    return ApplicationView(row[0], row[1], bool(row[2]), row[3], row[4])


def get_view(
    session: Session, user_id: uuid.UUID, application_id: uuid.UUID, cutoff: datetime
) -> ApplicationView | None:
    stmt = _view_select(cutoff).where(
        Application.user_id == user_id, Application.id == application_id
    )
    row = session.execute(stmt).one_or_none()
    return _view(row) if row else None


def list_views(
    session: Session,
    user_id: uuid.UUID,
    cutoff: datetime,
    *,
    status: str | None,
    sort: SortField,
    descending: bool,
    limit: int,
    after: PageCursor | None,
) -> list[ApplicationView]:
    """Keyset page of at most `limit` rows ordered by (sort key, id)."""
    key = _key_column(sort)
    stmt = _view_select(cutoff).where(Application.user_id == user_id)
    if status == GHOSTED:
        stmt = stmt.where(_ghosted(cutoff))
    elif status is not None:
        stmt = stmt.where(Application.status == ApplicationStatus(status), not_(_ghosted(cutoff)))
    if after is not None:
        pair, bound = tuple_(key, Application.id), tuple_(after.key, after.id)
        stmt = stmt.where(pair < bound if descending else pair > bound)
    order = (key.desc(), Application.id.desc()) if descending else (key.asc(), Application.id.asc())
    rows = session.execute(stmt.order_by(*order).limit(limit)).all()
    return [_view(row) for row in rows]
