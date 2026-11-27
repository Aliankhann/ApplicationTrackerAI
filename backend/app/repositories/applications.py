"""Application reads. Every query is scoped by user_id."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
    or_,
    select,
    tuple_,
)
from sqlalchemy.orm import Session

from app.errors import NotFound
from app.models import Application, ApplicationThread, EmailThread, StatusEvent
from app.services.classification import ApplicationStatus


def get_for_thread(
    session: Session, user_id: uuid.UUID, thread_id: uuid.UUID
) -> Application | None:
    """The application a thread belongs to (through the link table)."""
    stmt = (
        select(Application)
        .join(ApplicationThread, ApplicationThread.application_id == Application.id)
        .where(Application.user_id == user_id, ApplicationThread.thread_id == thread_id)
    )
    return session.scalars(stmt).one_or_none()


def link_thread(
    session: Session, user_id: uuid.UUID, application: Application, thread: EmailThread
) -> None:
    """Attach a thread to an application; both must be the user's."""
    if application.user_id != user_id or thread.user_id != user_id:
        raise NotFound("application")
    session.add(
        ApplicationThread(thread_id=thread.id, application_id=application.id, user_id=user_id)
    )
    session.flush()


@dataclass(frozen=True)
class MergeCandidate:
    application: Application
    domains: frozenset[str]  # sender domains of its linked threads


def merge_candidates(
    session: Session, user_id: uuid.UUID, thread: EmailThread, window: timedelta
) -> list[MergeCandidate]:
    """Live applications with a linked thread within `window` of this thread's messages, plus
    those with no linked thread left (their mail was disconnected and is being synced again)."""
    stmt = (
        select(Application, EmailThread.from_domain)
        .outerjoin(ApplicationThread, ApplicationThread.application_id == Application.id)
        .outerjoin(EmailThread, EmailThread.id == ApplicationThread.thread_id)
        .where(
            Application.user_id == user_id,
            Application.needs_review.is_(False),
            Application.dismissed_at.is_(None),
            or_(
                EmailThread.id.is_(None),
                and_(
                    EmailThread.user_id == user_id,
                    EmailThread.id != thread.id,
                    EmailThread.first_message_at <= thread.last_message_at + window,
                    EmailThread.last_message_at >= thread.first_message_at - window,
                ),
            ),
        )
        .order_by(Application.created_at, Application.id)
    )
    found: dict[uuid.UUID, tuple[Application, set[str]]] = {}
    for application, domain in session.execute(stmt):
        domains = found.setdefault(application.id, (application, set()))[1]
        if domain is not None:
            domains.add(domain)
    return [MergeCandidate(app, frozenset(domains)) for app, domains in found.values()]


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
NEEDS_REVIEW = "needs_review"
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
        Application.needs_review.is_(False),
        Application.status.in_(GHOSTABLE),
        EmailThread.last_sender_is_user.is_(True),
        Application.last_activity_at < cutoff,
    )


def _view_select(cutoff: datetime) -> Select[Any]:
    display = case(
        (Application.needs_review.is_(True), NEEDS_REVIEW),
        (_ghosted(cutoff), GHOSTED),
        else_=cast(Application.status, String),
    ).label("display_status")
    return (
        select(
            Application,
            display,
            Application.needs_review,
            EmailThread.subject,
            EmailThread.snippet,
        )
        .outerjoin(
            EmailThread,
            and_(
                EmailThread.id == Application.source_thread_id,
                EmailThread.user_id == Application.user_id,
            ),
        )
        .where(Application.dismissed_at.is_(None))
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
    elif status == NEEDS_REVIEW:
        stmt = stmt.where(Application.needs_review.is_(True))
    elif status is not None:
        stmt = stmt.where(
            Application.status == ApplicationStatus(status),
            Application.needs_review.is_(False),
            not_(_ghosted(cutoff)),
        )
    if after is not None:
        pair, bound = tuple_(key, Application.id), tuple_(after.key, after.id)
        stmt = stmt.where(pair < bound if descending else pair > bound)
    order = (key.desc(), Application.id.desc()) if descending else (key.asc(), Application.id.asc())
    rows = session.execute(stmt.order_by(*order).limit(limit)).all()
    return [_view(row) for row in rows]
