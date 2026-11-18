import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import CurrentUser, Db
from app.models import FollowUpTask
from app.repositories import followups as repo

router = APIRouter(prefix="/follow-ups", tags=["follow-ups"])

QueueState = Literal["pending", "drafted", "all"]


class FollowUpOut(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID
    company: str | None
    role: str | None
    step_index: int
    due_at: datetime
    state: str
    cancel_reason: str | None
    can_skip: bool


class DelayBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: Annotated[int, Field(ge=1, le=30)]


def _states(state: QueueState | None) -> tuple[str, ...]:
    if state in (None, "all"):
        return (repo.PENDING, repo.DRAFTED)
    return (state,)


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="not_found")


def _out_by_id(db: Db, user: CurrentUser, task_id: uuid.UUID) -> FollowUpOut:
    task = repo.get_owned(db, user.id, task_id)
    if task is None:
        raise _not_found()
    app = repo.application_of(db, user.id, task.application_id)
    return _out(task, app.company if app else None, app.role if app else None)


def _out(task: FollowUpTask, company: str | None, role: str | None) -> FollowUpOut:
    return FollowUpOut(
        id=task.id,
        application_id=task.application_id,
        company=company,
        role=role,
        step_index=task.step_index,
        due_at=task.due_at,
        state=task.state,
        cancel_reason=task.cancel_reason,
        can_skip=task.state == repo.PENDING,
    )


@router.get("", response_model=list[FollowUpOut])
def list_follow_ups(
    user: CurrentUser, db: Db, state: QueueState | None = None
) -> list[FollowUpOut]:
    rows = repo.list_queue(db, user.id, _states(state))
    return [_out(task, app.company, app.role) for task, app in rows]


def _transition(db: Db, user: CurrentUser, task_id: uuid.UUID, changed: bool) -> FollowUpOut:
    if not changed:
        db.rollback()
        if repo.get_owned(db, user.id, task_id) is None:
            raise _not_found()
        raise HTTPException(status_code=409, detail="not_pending")
    db.commit()
    return _out_by_id(db, user, task_id)


@router.post("/{task_id}/skip", response_model=FollowUpOut)
def skip_follow_up(task_id: uuid.UUID, user: CurrentUser, db: Db) -> FollowUpOut:
    return _transition(db, user, task_id, repo.skip_pending(db, user.id, task_id))


@router.post("/{task_id}/delay", response_model=FollowUpOut)
def delay_follow_up(task_id: uuid.UUID, body: DelayBody, user: CurrentUser, db: Db) -> FollowUpOut:
    return _transition(db, user, task_id, repo.delay_pending(db, user.id, task_id, body.days))
