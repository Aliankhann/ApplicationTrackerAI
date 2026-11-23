from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import (
    ClassifierDep,
    ClientFactoryDep,
    Clock,
    Config,
    CurrentUser,
    Db,
    Now,
)
from app.models import SyncStatus
from app.repositories import oauth_tokens as tokens_repo
from app.repositories import sync_state as sync_state_repo
from app.security.ratelimit import limit_by_user
from app.services.sync_runner import SyncOutcome, run_user_sync

router = APIRouter(prefix="/sync", tags=["sync"])

SYNC_LIMIT_PER_USER = 6


RunStatus = Literal["completed", "in_progress", "already_running", "revoked", "failed", "paused"]


class SyncRunOut(BaseModel):
    """`in_progress`: stopped at the short inline budget; the daily job and the next "Sync now"
    continue where this left off."""

    status: RunStatus
    reason: Literal["rate_limited"] | None = None


class SyncStatusOut(BaseModel):
    status: Literal["idle", "running", "error", "revoked", "paused"]
    last_synced_at: datetime | None
    initial_sync_done: bool
    last_error: str | None


_STATUS: dict[SyncOutcome, RunStatus] = {
    SyncOutcome.COMPLETED: "completed",
    SyncOutcome.PARTIAL: "in_progress",
    SyncOutcome.PAUSED: "paused",
    SyncOutcome.ALREADY_RUNNING: "already_running",
    SyncOutcome.REVOKED: "revoked",
    SyncOutcome.FAILED: "failed",
    SyncOutcome.USER_GONE: "failed",
}


@router.post(
    "",
    response_model=SyncRunOut,
    response_model_exclude_none=True,
    dependencies=[limit_by_user("sync", SYNC_LIMIT_PER_USER)],
)
def run_sync_now(
    user: CurrentUser,
    db: Db,
    clock: Clock,
    settings: Config,
    client_factory: ClientFactoryDep,
    classifier: ClassifierDep,
) -> SyncRunOut:
    """Sync inline within a short time budget (no background tasks on serverless). The lease in
    sync_state keeps it to one sync per user at a time."""
    if tokens_repo.active_row(db, user.id) is None:
        raise HTTPException(status_code=409, detail="gmail_not_connected")
    now = clock()
    outcome = run_user_sync(
        db,
        user.id,
        now,
        client_factory,
        classifier,
        deadline=now + timedelta(seconds=settings.manual_sync_budget_seconds),
        clock=clock,
        ensure_progress=False,  # the daily job guarantees progress; a manual press may stop early
    )
    paused = outcome is SyncOutcome.PAUSED
    return SyncRunOut(status=_STATUS[outcome], reason="rate_limited" if paused else None)


@router.get("", response_model=SyncStatusOut)
def sync_status(user: CurrentUser, db: Db, now: Now) -> SyncStatusOut:
    state = sync_state_repo.get(db, user.id)
    if state is None:
        return SyncStatusOut(
            status="idle", last_synced_at=None, initial_sync_done=False, last_error=None
        )
    stale = state.status == SyncStatus.RUNNING.value and not sync_state_repo.lease_active(
        state, now
    )
    return SyncStatusOut(
        status="idle" if stale else SyncStatus(state.status).value,
        last_synced_at=state.last_synced_at,
        initial_sync_done=state.initial_sync_done,
        last_error=state.last_error,
    )
