"""Applications from classified threads: forward-only status, timeline, manual lock."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import NotFound
from app.models import Application, EmailThread, StatusEvent
from app.providers.classifier.types import ClassificationResult
from app.repositories import applications as applications_repo
from app.repositories import threads as threads_repo
from app.services.classification import ApplicationStatus, apply_result
from app.services.extraction import Extracted

# Rejected is terminal but reachable from any status, so it is not ranked.
STATUS_ORDER: tuple[ApplicationStatus, ...] = (
    ApplicationStatus.APPLIED,
    ApplicationStatus.ONLINE_ASSESSMENT,
    ApplicationStatus.INTERVIEW,
    ApplicationStatus.OFFER,
)
REASON_CREATED = "created"
REASON_MANUAL = "manual"
MAX_COMPANY = 80
MAX_ROLE = 120


def _require_aware(now: datetime) -> None:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")


def _cap(value: str | None, limit: int) -> str | None:
    return value[:limit] if value is not None else None


def _can_move(current: ApplicationStatus, new: ApplicationStatus) -> bool:
    if current == ApplicationStatus.REJECTED or new == current:
        return False
    if new == ApplicationStatus.REJECTED:
        return True
    return STATUS_ORDER.index(new) > STATUS_ORDER.index(current)


def _reason(result: ClassificationResult) -> str:
    return f"classifier:{result.rule_id or result.method}"


def _add_event(
    session: Session,
    application: Application,
    from_status: ApplicationStatus | None,
    reason: str,
    now: datetime,
) -> None:
    session.add(
        StatusEvent(
            application_id=application.id,
            from_status=from_status,
            to_status=application.status,
            reason=reason,
            at=now,
        )
    )


def _create(
    session: Session,
    user_id: uuid.UUID,
    thread: EmailThread,
    status: ApplicationStatus,
    extracted: Extracted,
    now: datetime,
) -> Application:
    application = Application(
        user_id=user_id,
        company=_cap(extracted.company, MAX_COMPANY),
        role=_cap(extracted.role, MAX_ROLE),
        status=status,
        source_thread_id=thread.id,
        applied_at=thread.first_message_at if status == ApplicationStatus.APPLIED else None,
        last_activity_at=now,
        status_locked=False,
    )
    session.add(application)
    session.flush()
    _add_event(session, application, None, REASON_CREATED, now)
    return application


def _thread_start(session: Session, application: Application) -> datetime | None:
    if application.source_thread_id is None:
        return None
    thread = session.get(EmailThread, application.source_thread_id)
    return thread.first_message_at if thread else None


def _lock_thread(session: Session, user_id: uuid.UUID, thread: EmailThread) -> None:
    """Serialize concurrent callers on the thread row; NotFound if it is not the user's."""
    stmt = (
        select(EmailThread.id)
        .where(EmailThread.id == thread.id, EmailThread.user_id == user_id)
        .with_for_update()
    )
    if session.scalar(stmt) is None:
        raise NotFound("thread")


def _try_create(
    session: Session,
    user_id: uuid.UUID,
    thread: EmailThread,
    status: ApplicationStatus,
    extracted: Extracted,
    now: datetime,
) -> Application | None:
    """Create inside a savepoint; None when another caller already created it."""
    try:
        with session.begin_nested():
            return _create(session, user_id, thread, status, extracted, now)
    except IntegrityError:
        return None


def _advance(
    session: Session,
    application: Application,
    new_status: ApplicationStatus,
    reason: str,
    extracted: Extracted,
    now: datetime,
) -> None:
    application.last_activity_at = now
    application.company = application.company or _cap(extracted.company, MAX_COMPANY)
    application.role = application.role or _cap(extracted.role, MAX_ROLE)
    if application.status_locked or not _can_move(application.status, new_status):
        return
    previous = application.status
    application.status = new_status
    _add_event(session, application, previous, reason, now)


def record_classification(
    session: Session,
    user_id: uuid.UUID,
    thread: EmailThread,
    result: ClassificationResult,
    extracted: Extracted,
    now: datetime,
) -> Application | None:
    """Store the classification, then create or advance the thread's application."""
    _require_aware(now)
    _lock_thread(session, user_id, thread)
    threads_repo.add_classification(session, user_id, thread, result)
    application = applications_repo.get_for_thread(session, user_id, thread.id)
    new_status = apply_result(application.status if application else None, result)
    if new_status is None:
        if application is not None:
            application.last_activity_at = now
        session.flush()
        return application
    if application is None:
        application = _try_create(session, user_id, thread, new_status, extracted, now)
        if application is not None:
            return application
        application = applications_repo.get_for_thread(session, user_id, thread.id)
        if application is None:
            raise RuntimeError("application vanished after a unique conflict")
    _advance(session, application, new_status, _reason(result), extracted, now)
    session.flush()
    return application


def set_status_manually(
    session: Session,
    user_id: uuid.UUID,
    application_id: uuid.UUID,
    status: ApplicationStatus,
    now: datetime,
) -> Application:
    """Any direction; locks the status against later classifier changes."""
    _require_aware(now)
    application = applications_repo.get(session, user_id, application_id)
    if application is None:
        raise NotFound("application")
    previous = application.status
    application.status_locked = True
    application.last_activity_at = now
    if status != previous:
        application.status = status
        if status == ApplicationStatus.APPLIED and application.applied_at is None:
            application.applied_at = _thread_start(session, application) or now
        _add_event(session, application, previous, REASON_MANUAL, now)
    session.flush()
    return application


def edit_details(
    session: Session,
    user_id: uuid.UUID,
    application_id: uuid.UUID,
    *,
    company: str | None = None,
    role: str | None = None,
    followups_paused: bool | None = None,
) -> Application:
    """User edits; None leaves a field alone. Extraction only fills nulls, so edits stick."""
    application = applications_repo.get(session, user_id, application_id)
    if application is None:
        raise NotFound("application")
    if company is not None:
        application.company = _cap(company, MAX_COMPANY)
    if role is not None:
        application.role = _cap(role, MAX_ROLE)
    if followups_paused is not None:
        application.followups_paused = followups_paused
    session.flush()
    return application
