import hmac
import uuid
from typing import Any, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import (
    Clock,
    Config,
    CurrentSession,
    CurrentUser,
    Db,
    EmailDep,
    Now,
    OidcDep,
    RevokerDep,
    clear_session_cookies,
    require_google_config,
    set_cookie,
    set_session_cookies,
)
from app.log import get_logger
from app.models import AuditAction
from app.providers.email import EmailSender, EmailSendError
from app.providers.google.oidc import Identity, OidcError, new_pkce, random_token
from app.providers.google.revoke import RevokerNotConfigured
from app.repositories import audit as audit_repo
from app.repositories import invite_codes
from app.security import sessions, signed_cookie
from app.security.ratelimit import limit_by_ip
from app.services import account, signin

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


# --- Sign-in (US-11, US-12, US-92) ----------------------------------------------------------
# Flow state (state, PKCE verifier, nonce, invite claim) lives in a signed HttpOnly cookie, see
# app.security.signed_cookie. Every failure redirects to the frontend with a stable ?error= code.

INVITE_LIMIT_PER_IP = 10
INVITE_LIMIT_GLOBAL = 50
SIGN_IN_LIMIT_PER_IP = 30
SIGN_IN_FAILED = "sign_in_failed"
SIGN_IN_CANCELLED = "sign_in_cancelled"
PUBLIC_ERRORS = frozenset(
    {signin.NOT_INVITED, signin.ACCOUNT_DISABLED, SIGN_IN_CANCELLED, SIGN_IN_FAILED}
)


class InviteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(max_length=64)


@router.post(
    "/auth/invite",
    status_code=204,
    dependencies=[
        Depends(require_google_config),
        limit_by_ip("invite", INVITE_LIMIT_PER_IP, INVITE_LIMIT_GLOBAL),
    ],
)
def submit_invite(body: InviteBody, db: Db, settings: Config, now: Now, response: Response) -> None:
    """Check a code WITHOUT using it; remember it in a signed cookie for the sign-in callback."""
    invite = invite_codes.find_redeemable(db, body.code, now)
    if invite is None:  # unknown, used, expired, and malformed look identical
        raise HTTPException(status_code=400, detail="invalid_invite")
    claim = signed_cookie.sign(
        signed_cookie.INVITE_KIND, {"invite_id": str(invite.id)}, now, settings
    )
    set_cookie(
        response, settings.invite_cookie, claim, signed_cookie.INVITE_MAX_AGE, True, settings
    )


def _invite_claim(request: Request, settings: Config, now: Now) -> uuid.UUID | None:
    raw = request.cookies.get(settings.invite_cookie)
    payload = (
        signed_cookie.verify(
            signed_cookie.INVITE_KIND, raw, now, signed_cookie.INVITE_MAX_AGE, settings
        )
        if raw
        else None
    )
    return _parse_uuid(payload.get("invite_id")) if payload else None


def _parse_uuid(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


@router.get(
    "/auth/google/start",
    status_code=302,
    response_class=RedirectResponse,
    dependencies=[limit_by_ip("signin", SIGN_IN_LIMIT_PER_IP)],
)
def google_start(request: Request, settings: Config, now: Now, oidc: OidcDep) -> RedirectResponse:
    state, nonce, pkce = random_token(), random_token(), new_pkce()
    invite_id = _invite_claim(request, settings, now)
    flow = {
        "state": state,
        "verifier": pkce.verifier,
        "nonce": nonce,
        "invite_id": str(invite_id) if invite_id else None,
    }
    url = oidc.build_authorization_url(state, pkce.challenge, nonce)
    response = RedirectResponse(url, status_code=302)
    value = signed_cookie.sign(signed_cookie.FLOW_KIND, flow, now, settings)
    set_cookie(response, settings.oauth_cookie, value, signed_cookie.FLOW_MAX_AGE, True, settings)
    return response


def _sign_in_redirect(settings: Config, error: str | None) -> RedirectResponse:
    query = f"?{urlencode({'error': error})}" if error else ""
    return RedirectResponse(f"{settings.frontend_origin}/sign-in{query}", status_code=302)


def _clear_flow_cookies(response: Response, settings: Config) -> None:
    set_cookie(response, settings.oauth_cookie, "", 0, True, settings)
    set_cookie(response, settings.invite_cookie, "", 0, True, settings)


def _fail(db: Db, settings: Config, reason: str, public: str = SIGN_IN_FAILED) -> RedirectResponse:
    """Write nothing, log only the stable reason, and send the browser back to /sign-in."""
    db.rollback()
    logger.warning("auth.callback_rejected", extra={"error_code": reason})
    response = _sign_in_redirect(settings, public if public in PUBLIC_ERRORS else SIGN_IN_FAILED)
    _clear_flow_cookies(response, settings)
    return response


@router.get(
    "/auth/google/callback",
    status_code=302,
    response_class=RedirectResponse,
    dependencies=[limit_by_ip("signin", SIGN_IN_LIMIT_PER_IP)],
)
def google_callback(
    request: Request,
    db: Db,
    settings: Config,
    now: Now,
    oidc: OidcDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if error is not None:
        cancelled = error == "access_denied"
        return _fail(
            db, settings, "google_error", SIGN_IN_CANCELLED if cancelled else SIGN_IN_FAILED
        )
    raw = request.cookies.get(settings.oauth_cookie)
    flow = signed_cookie.verify(
        signed_cookie.FLOW_KIND, raw or "", now, signed_cookie.FLOW_MAX_AGE, settings
    )
    if flow is None:
        return _fail(db, settings, "flow_invalid")
    if not state or not hmac.compare_digest(state.encode(), str(flow["state"]).encode()):
        return _fail(db, settings, "state_mismatch")
    if not code:
        return _fail(db, settings, "code_missing")
    try:
        token = oidc.exchange_code(code, str(flow["verifier"]))
        identity = oidc.verify_id_token(token.id_token, str(flow["nonce"]))
    except OidcError as exc:
        return _fail(db, settings, exc.code)
    return _admit_and_start_session(request, db, settings, now, identity, flow)


def _admit_and_start_session(
    request: Request, db: Db, settings: Config, now: Now, identity: Identity, flow: dict[str, Any]
) -> RedirectResponse:
    try:
        user = signin.admit(db, identity, _parse_uuid(flow.get("invite_id")), settings, now)
        # Always a brand-new session: a session id from before sign-in is never promoted.
        raw_token, csrf_token, _ = sessions.create_session(
            db, user.id, now, settings, request.headers.get("user-agent")
        )
        audit_repo.record(db, user.id, AuditAction.LOGIN, now)
        db.commit()
    except signin.SignInRejected as exc:
        return _fail(db, settings, exc.code, exc.code)
    response = RedirectResponse(f"{settings.frontend_origin}/app", status_code=302)
    set_session_cookies(response, raw_token, csrf_token, settings)
    _clear_flow_cookies(response, settings)
    return response
