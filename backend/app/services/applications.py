"""Applications from classified threads: forward-only status, timeline, manual lock.

One application (card) can own many threads (`application_threads`): a thread joins an existing
card when company and role match (`merging`), else it starts one. Status moves forward-only across
all of its threads. Threads that stay undecided become a "needs review" card with a suggested
label, which the user confirms, changes or dismisses."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import InvalidOperation, NotFound
from app.models import Application, EmailThread, StatusEvent
from app.providers.classifier.types import ClassificationResult, Label
from app.repositories import applications as applications_repo
from app.repositories import threads as threads_repo
from app.services.classification import ApplicationStatus, apply_result, status_for_label
from app.services.extraction import Extracted
from app.services.merging import find_merge_target

# Rejected is terminal but reachable from any status, so it is not ranked.
STATUS_ORDER: tuple[ApplicationStatus, ...] = (
    ApplicationStatus.APPLIED,
    ApplicationStatus.ONLINE_ASSESSMENT,
    ApplicationStatus.INTERVIEW,
    ApplicationStatus.OFFER,
)
REASON_CREATED = "created"
REASON_MANUAL = "manual"
REASON_REVIEWED = "reviewed"
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
    *,
    suggested: Label | None = None,
    review: bool = False,
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
        needs_review=review,
        suggested_label=str(suggested) if review and suggested else None,
    )
    session.add(application)
    session.flush()
    applications_repo.link_thread(session, user_id, application, thread)
    if not review:
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
    *,
    suggested: Label | None = None,
    review: bool = False,
) -> Application | None:
    """Create inside a savepoint; None when another caller already created it."""
    try:
        with session.begin_nested():
            return _create(
                session, user_id, thread, status, extracted, now, suggested=suggested, review=review
            )
    except IntegrityError:
        return None


def _attach(
    session: Session,
    user_id: uuid.UUID,
    application: Application,
    thread: EmailThread,
    extracted: Extracted,
) -> None:
    """Add the thread to an existing card; the card keeps its own company and role."""
    applications_repo.link_thread(session, user_id, application, thread)
    application.company = application.company or _cap(extracted.company, MAX_COMPANY)
    application.role = application.role or _cap(extracted.role, MAX_ROLE)
    applied = thread.first_message_at
    if application.applied_at is not None and applied < application.applied_at:
        application.applied_at = applied


def _resolve_review(
    session: Session, application: Application, status: ApplicationStatus, now: datetime
) -> None:
    """A decisive result for a needs-review card: it becomes a normal card at that status."""
    application.needs_review = False
    application.suggested_label = None
    application.dismissed_at = None
    application.status = status
    application.last_activity_at = now
    _add_event(session, application, None, REASON_REVIEWED, now)


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
    if application.needs_review:
        _resolve_review(session, application, new_status, now)
        return
    if application.status_locked or not _can_move(application.status, new_status):
        return
    previous = application.status
    application.status = new_status
    _add_event(session, application, previous, reason, now)


def _create_or_merge(
    session: Session,
    user_id: uuid.UUID,
    thread: EmailThread,
    status: ApplicationStatus,
    extracted: Extracted,
    now: datetime,
) -> Application | None:
    """The card a new thread belongs to: an existing one it merges into, else a new one. The
    status of a merge target moves forward only (the caller advances it)."""
    target = find_merge_target(session, user_id, thread, extracted)
    if target is None:
        return _try_create(session, user_id, thread, status, extracted, now)
    _attach(session, user_id, target, thread, extracted)
    return target


def record_classification(
    session: Session,
    user_id: uuid.UUID,
    thread: EmailThread,
    result: ClassificationResult,
    extracted: Extracted,
    now: datetime,
    message_id: str | None = None,
    message_at: datetime | None = None,
) -> Application | None:
    """Store the classification (per message when `message_id` is given), then create, merge
    into or advance the thread's application. Forward-only across all of its threads. A dismissed
    card is revived only by a decisive message sent after it was dismissed (`message_at`), never
    by re-reading old mail."""
    _require_aware(now)
    _lock_thread(session, user_id, thread)
    threads_repo.add_classification(session, user_id, thread, result, message_id)
    application = applications_repo.get_for_thread(session, user_id, thread.id)
    new_status = apply_result(application.status if application else None, result)
    if (
        application is not None
        and application.dismissed_at is not None
        and (message_at is None or message_at <= application.dismissed_at)
    ):
        new_status = None  # old mail of a card the user dismissed
    if new_status is None:
        if application is not None:
            application.last_activity_at = now
        session.flush()
        return application
    if application is None:
        application = _create_or_merge(session, user_id, thread, new_status, extracted, now)
        if application is None:
            application = applications_repo.get_for_thread(session, user_id, thread.id)
        if application is None:
            raise RuntimeError("application vanished after a unique conflict")
        if application.source_thread_id == thread.id:
            session.flush()
            return application
    _advance(session, application, new_status, _reason(result), extracted, now)
    session.flush()
    return application


def record_undecided(
    session: Session,
    user_id: uuid.UUID,
    thread: EmailThread,
    suggested: Label | None,
    extracted: Extracted,
    now: datetime,
) -> Application | None:
    """A job thread no message decided. It joins the card it matches (nothing else changes), else
    becomes a needs-review card carrying the suggested label. A card the thread already has
    (a dismissed one included) is left alone apart from a fresher suggestion."""
    _require_aware(now)
    _lock_thread(session, user_id, thread)
    application = applications_repo.get_for_thread(session, user_id, thread.id)
    if application is None:
        target = find_merge_target(session, user_id, thread, extracted)
        if target is not None:
            _attach(session, user_id, target, thread, extracted)
            application = target
        else:
            status = status_for_label(suggested) or ApplicationStatus.APPLIED
            application = _try_create(
                session, user_id, thread, status, extracted, now, suggested=suggested, review=True
            )
    elif application.needs_review and suggested is not None:
        application.suggested_label = str(suggested)
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
    was_review = application.needs_review
    application.status_locked = True
    application.needs_review = False
    application.suggested_label = None
    application.last_activity_at = now
    if status != previous or was_review:
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


def confirm_review(
    session: Session, user_id: uuid.UUID, application_id: uuid.UUID, now: datetime
) -> Application:
    """Accept the suggested label of a needs-review card as its status. The card becomes a normal
    one and is not locked: later mail in its threads can still move it (only an explicit status
    change by the user locks)."""
    _require_aware(now)
    application = applications_repo.get(session, user_id, application_id)
    if application is None or application.dismissed_at is not None:
        raise NotFound("application")
    status = None
    if application.needs_review and application.suggested_label:
        status = status_for_label(Label(application.suggested_label))
    if status is None:
        raise InvalidOperation("nothing to confirm")
    _resolve_review(session, application, status, now)
    session.flush()
    return application


def dismiss_review(
    session: Session, user_id: uuid.UUID, application_id: uuid.UUID, now: datetime
) -> None:
    """Hide a needs-review card for good: its thread stays linked, so a later sync does not
    recreate it (a decisive message in the thread still brings it back)."""
    _require_aware(now)
    application = applications_repo.get(session, user_id, application_id)
    if application is None or application.dismissed_at is not None:
        raise NotFound("application")
    if not application.needs_review:
        raise InvalidOperation("only a card that needs review can be dismissed")
    application.dismissed_at = now
    session.flush()
