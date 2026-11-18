import uuid

from fastapi import APIRouter, Response
from pydantic import BaseModel

from app.api.deps import (
    Clock,
    Config,
    CurrentSession,
    CurrentUser,
    Db,
    clear_session_cookies,
)
from app.security import sessions

router = APIRouter(tags=["auth"])


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    timezone: str | None


@router.get("/me", response_model=MeResponse)
def me(user: CurrentUser) -> MeResponse:
    return MeResponse(id=user.id, email=user.email, timezone=user.timezone)


@router.post("/auth/logout", status_code=204, tags=["auth"])
def logout(row: CurrentSession, db: Db, settings: Config, clock: Clock, response: Response) -> None:
    sessions.revoke(db, row.id, clock())
    db.commit()
    clear_session_cookies(response, settings)
