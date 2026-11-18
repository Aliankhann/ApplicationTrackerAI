import uuid
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict

from app.api.deps import (
    Clock,
    Config,
    CurrentSession,
    CurrentUser,
    Db,
    EmailDep,
    Now,
    RevokerDep,
    clear_session_cookies,
)
from app.log import get_logger
from app.models import AuditAction
from app.providers.email import EmailSender, EmailSendError
from app.providers.google.revoke import RevokerNotConfigured
from app.repositories import audit as audit_repo
from app.security import sessions
from app.services import account

router = APIRouter(tags=["auth"])
logger = get_logger("app.auth")

ERROR_EMAIL = "email_failed"


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    timezone: str | None


class DeleteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: Literal["DELETE"]


class DeleteOut(BaseModel):
    deleted: Literal[True]
    revoked_at_google: bool | None


@router.get("/me", response_model=MeResponse)
def me(user: CurrentUser) -> MeResponse:
    return MeResponse(id=user.id, email=user.email, timezone=user.timezone)


@router.delete("/me", response_model=DeleteOut)
def delete_me(
    body: DeleteBody,
    user: CurrentUser,
    db: Db,
    settings: Config,
    now: Now,
    revoker: RevokerDep,
    sender: EmailDep,
    response: Response,
) -> DeleteOut:
    """Revoke at Google (best effort, never blocks), then wipe every row in one transaction."""
    address = user.email
    try:
        revoked = account.revoke_at_google(db, user.id, revoker)
    except RevokerNotConfigured:
        revoked = False
    account.delete_account(db, user.id, now)
    db.commit()
    clear_session_cookies(response, settings)
    _confirm_by_email(sender, address)
    return DeleteOut(deleted=True, revoked_at_google=revoked)


def _confirm_by_email(sender: EmailSender, address: str) -> None:
    try:
        sender.send_deletion_confirmation(address)
    except Exception as exc:
        code = exc.code if isinstance(exc, EmailSendError) else ERROR_EMAIL
        logger.warning("account.confirmation_failed", extra={"error_code": code})


@router.post("/auth/logout", status_code=204, tags=["auth"])
def logout(row: CurrentSession, db: Db, settings: Config, clock: Clock, response: Response) -> None:
    now = clock()
    sessions.revoke(db, row.id, now)
    audit_repo.record(db, row.user_id, AuditAction.LOGOUT, now)
    db.commit()
    clear_session_cookies(response, settings)
