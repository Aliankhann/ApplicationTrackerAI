from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict

from app.api.deps import (
    Config,
    CurrentUser,
    Db,
    MaybeUser,
    Now,
    OidcDep,
    RevokerDep,
    require_google_config,
    set_cookie,
)
from app.log import get_logger
from app.providers.google.revoke import RevokerNotConfigured
from app.providers.google.scopes import can_compose
from app.repositories import oauth_tokens as tokens_repo
from app.security import signed_cookie
from app.services import account, gmail_connect

router = APIRouter(prefix="/gmail", tags=["gmail"])
logger = get_logger("app.gmail")


class DisconnectOut(BaseModel):
    revoked_at_google: bool | None


@router.post("/disconnect", response_model=DisconnectOut)
def disconnect(user: CurrentUser, db: Db, now: Now, revoker: RevokerDep) -> DisconnectOut:
    try:
        result = account.disconnect_gmail(db, user.id, revoker, now)
    except account.SyncInProgress:
        db.rollback()
        raise HTTPException(status_code=409, detail="sync_in_progress") from None
    except RevokerNotConfigured:
        db.rollback()
        raise HTTPException(status_code=503, detail="revocation_unavailable") from None
    db.commit()
    return DisconnectOut(revoked_at_google=result.revoked_at_google)


class GmailStatusOut(BaseModel):
    connected: bool
    followups_enabled: bool


@router.get("/status", response_model=GmailStatusOut)
def status(user: CurrentUser, db: Db) -> GmailStatusOut:
    row = tokens_repo.active_row(db, user.id)
    return GmailStatusOut(
        connected=row is not None,
        followups_enabled=row is not None and can_compose(row.scopes),
    )


class GmailConnectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    followups: bool = False


class GmailConnectOut(BaseModel):
    authorize_url: str


@router.post(
    "/connect", response_model=GmailConnectOut, dependencies=[Depends(require_google_config)]
)
def connect(
    user: CurrentUser,
    settings: Config,
    now: Now,
    oidc: OidcDep,
    response: Response,
    body: GmailConnectBody | None = None,
) -> GmailConnectOut:
    """Start consent for gmail.readonly (plus gmail.compose when `followups`). The frontend then
    navigates to `authorize_url`; the flow state rides in a signed cookie bound to this user."""
    auth = gmail_connect.begin(oidc, user, body is not None and body.followups, settings, now)
    set_cookie(
        response,
        settings.connect_cookie,
        auth.cookie_value,
        signed_cookie.FLOW_MAX_AGE,
        True,
        settings,
    )
    return GmailConnectOut(authorize_url=auth.url)


def _settings_redirect(settings: Config, code: str) -> RedirectResponse:
    public = code if code in gmail_connect.PUBLIC_CODES else gmail_connect.CONNECT_FAILED
    query = urlencode({"gmail_error": public})
    response = RedirectResponse(f"{settings.frontend_origin}/app/settings?{query}", status_code=302)
    set_cookie(response, settings.connect_cookie, "", 0, True, settings)
    return response


def _reject(db: Db, settings: Config, code: str) -> RedirectResponse:
    """Write nothing, log only the stable code, and send the browser back to settings."""
    db.rollback()
    logger.warning("gmail.connect_rejected", extra={"error_code": code})
    return _settings_redirect(settings, code)


@router.get("/callback", status_code=302, response_class=RedirectResponse)
def callback(
    request: Request,
    user: MaybeUser,
    db: Db,
    settings: Config,
    now: Now,
    oidc: OidcDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Google redirects here. Needs the session cookie and a connect-flow cookie bound to it."""
    if user is None:
        return _reject(db, settings, gmail_connect.SESSION_REQUIRED)
    try:
        flow = gmail_connect.read_flow(
            request.cookies.get(settings.connect_cookie), user, state, now, settings
        )
        if error is not None:
            raise gmail_connect.ConnectFailed(
                gmail_connect.ACCESS_DENIED
                if error == "access_denied"
                else gmail_connect.GOOGLE_ERROR
            )
        if not code:
            raise gmail_connect.ConnectFailed(gmail_connect.CONNECT_FAILED)
        outcome = gmail_connect.complete(db, user, oidc, settings, flow, code, now)
        db.commit()
    except gmail_connect.ConnectFailed as exc:
        return _reject(db, settings, exc.code)
    if outcome.followups_denied:
        logger.warning(
            "gmail.connect_rejected", extra={"error_code": gmail_connect.FOLLOWUPS_DENIED}
        )
        return _settings_redirect(settings, gmail_connect.FOLLOWUPS_DENIED)
    response = RedirectResponse(f"{settings.frontend_origin}/app?connected=1", status_code=302)
    set_cookie(response, settings.connect_cookie, "", 0, True, settings)
    return response
