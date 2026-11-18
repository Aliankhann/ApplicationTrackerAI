from datetime import datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Response
from pydantic import BaseModel

from app.api.deps import CurrentUser, Db, Now, SyncLauncher
from app.models import SyncStatus
from app.repositories import oauth_tokens as tokens_repo
from app.repositories import sync_state as sync_state_repo
from app.security.ratelimit import limit_by_user

router = APIRouter(prefix="/sync", tags=["sync"])

SYNC_LIMIT_PER_USER = 6


class SyncStartOut(BaseModel):
    status: Literal["started", "already_running"]


class SyncStatusOut(BaseModel):
    status: Literal["idle", "running", "error", "revoked"]
    last_synced_at: datetime | None
    initial_sync_done: bool
    last_error: str | None


@router.post(
    "",
    status_code=202,
    response_model=SyncStartOut,
    dependencies=[limit_by_user("sync", SYNC_LIMIT_PER_USER)],
)
def start_sync(
    user: CurrentUser,
    db: Db,
    now: Now,
    launch: SyncLauncher,
    background: BackgroundTasks,
    response: Response,
) -> SyncStartOut:
    """Start a sync in the background; the lease in sync_state keeps it to one at a time."""
    if tokens_repo.active_row(db, user.id) is None:
        raise HTTPException(status_code=409, detail="gmail_not_connected")
    if sync_state_repo.lease_active(sync_state_repo.get(db, user.id), now):
        response.status_code = 200
        return SyncStartOut(status="already_running")
    background.add_task(launch, user.id)
    return SyncStartOut(status="started")


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
