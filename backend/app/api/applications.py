import base64
import binascii
import uuid
from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.deps import Config, CurrentUser, Db, Now
from app.errors import NotFound
from app.repositories import applications as repo
from app.services import applications as service
from app.services.classification import ApplicationStatus
from app.services.templates import strip_unsafe

router = APIRouter(prefix="/applications", tags=["applications"])

StatusFilter = Literal["applied", "online_assessment", "interview", "offer", "rejected", "ghosted"]
CURSOR_PARTS = 3


class ApplicationOut(BaseModel):
    id: uuid.UUID
    company: str | None
    role: str | None
    status: ApplicationStatus
    display_status: str
    applied_at: datetime | None
    last_activity_at: datetime
    status_locked: bool
    needs_review: bool
    followups_paused: bool


class ApplicationDetail(ApplicationOut):
    subject: str | None
    snippet: str | None


class ApplicationPage(BaseModel):
    items: list[ApplicationOut]
    next_cursor: str | None


class EventOut(BaseModel):
    from_status: ApplicationStatus | None
    to_status: ApplicationStatus
    reason: str
    at: datetime


class ApplicationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ApplicationStatus | None = None
    company: str | None = Field(default=None, min_length=1, max_length=80)
    role: str | None = Field(default=None, min_length=1, max_length=120)
    followups_paused: bool | None = None

    @field_validator("company", "role", mode="after")
    @classmethod
    def _clean(cls, value: str | None) -> str:
        cleaned = strip_unsafe(value).strip() if value is not None else ""
        if not cleaned:
            raise ValueError("must not be empty or null")
        return cleaned

    @field_validator("status", "followups_paused", mode="after")
    @classmethod
    def _not_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("must not be null")
        return value


def _out(view: repo.ApplicationView) -> ApplicationOut:
    return ApplicationOut.model_validate(_fields(view))


def _fields(view: repo.ApplicationView) -> dict[str, object]:
    a = view.application
    return {
        "id": a.id,
        "company": a.company,
        "role": a.role,
        "status": a.status,
        "display_status": view.display_status,
        "applied_at": a.applied_at,
        "last_activity_at": a.last_activity_at,
        "status_locked": a.status_locked,
        "needs_review": view.needs_review,
        "followups_paused": a.followups_paused,
    }


def _detail(view: repo.ApplicationView) -> ApplicationDetail:
    fields = {**_fields(view), "subject": view.subject, "snippet": view.snippet}
    return ApplicationDetail.model_validate(fields)


def encode_cursor(sort: repo.SortField, key: datetime, row_id: uuid.UUID) -> str:
    raw = f"{sort}|{key.isoformat()}|{row_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(raw: str, sort: repo.SortField) -> repo.PageCursor:
    """Strict: any malformed or mismatched cursor raises ValueError."""
    try:
        parts = base64.urlsafe_b64decode(raw.encode("ascii")).decode().split("|")
        if len(parts) != CURSOR_PARTS or parts[0] != sort:
            raise ValueError("cursor does not match this sort")
        key = datetime.fromisoformat(parts[1])
        if key.tzinfo is None:
            raise ValueError("cursor time must be timezone-aware")
        return repo.PageCursor(key, uuid.UUID(parts[2]))
    except (binascii.Error, UnicodeError, ValueError) as exc:
        raise ValueError("bad cursor") from exc


@router.get("", response_model=ApplicationPage)
def list_applications(
    user: CurrentUser,
    db: Db,
    settings: Config,
    now: Now,
    status: StatusFilter | None = None,
    sort: Literal["last_activity", "applied_at"] = "last_activity",
    order: Literal["desc", "asc"] = "desc",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=300)] = None,
) -> ApplicationPage:
    try:
        after = decode_cursor(cursor, sort) if cursor else None
    except ValueError:
        raise HTTPException(status_code=400, detail="bad_cursor") from None
    cutoff = now - timedelta(days=settings.ghosted_after_days)
    views = repo.list_views(
        db,
        user.id,
        cutoff,
        status=status,
        sort=sort,
        descending=order == "desc",
        limit=limit + 1,
        after=after,
    )
    page = views[:limit]
    more = len(views) > limit
    last = page[-1].application if page else None
    next_cursor = encode_cursor(sort, repo.sort_key(last, sort), last.id) if more and last else None
    return ApplicationPage(items=[_out(v) for v in page], next_cursor=next_cursor)


def _require_view(
    db: Db, user: CurrentUser, settings: Config, now: Now, application_id: uuid.UUID
) -> repo.ApplicationView:
    cutoff = now - timedelta(days=settings.ghosted_after_days)
    view = repo.get_view(db, user.id, application_id, cutoff)
    if view is None:
        raise HTTPException(status_code=404, detail="not_found")
    return view


@router.get("/{application_id}", response_model=ApplicationDetail)
def get_application(
    application_id: uuid.UUID, user: CurrentUser, db: Db, settings: Config, now: Now
) -> ApplicationDetail:
    return _detail(_require_view(db, user, settings, now, application_id))


@router.get("/{application_id}/events", response_model=list[EventOut])
def list_events(application_id: uuid.UUID, user: CurrentUser, db: Db) -> list[EventOut]:
    if repo.get(db, user.id, application_id) is None:
        raise HTTPException(status_code=404, detail="not_found")
    events = repo.list_events(db, user.id, application_id)
    return [
        EventOut(from_status=e.from_status, to_status=e.to_status, reason=e.reason, at=e.at)
        for e in events
    ]


@router.patch("/{application_id}", response_model=ApplicationDetail)
def patch_application(
    application_id: uuid.UUID,
    body: ApplicationPatch,
    user: CurrentUser,
    db: Db,
    settings: Config,
    now: Now,
) -> ApplicationDetail:
    try:
        if body.status is not None:
            service.set_status_manually(db, user.id, application_id, body.status, now)
        service.edit_details(
            db,
            user.id,
            application_id,
            company=body.company,
            role=body.role,
            followups_paused=body.followups_paused,
        )
    except NotFound:
        db.rollback()
        raise HTTPException(status_code=404, detail="not_found") from None
    db.commit()
    return _detail(_require_view(db, user, settings, now, application_id))
