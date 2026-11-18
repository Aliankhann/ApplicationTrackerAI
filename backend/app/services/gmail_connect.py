"""Connect Gmail (incremental consent): build the authorization URL, finish the code exchange.

A refresh token is written only after every check passes; a failure raises `ConnectFailed`
with a stable code and writes nothing. Tokens, codes, and Google's responses are never logged.
"""

import hmac
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.config import Settings
from app.log import get_logger
from app.models import AuditAction, User
from app.providers.google.oidc import GoogleOidc, OidcError, new_pkce, random_token
from app.providers.google.scopes import can_compose, can_read, connect_scopes, parse_scopes
from app.repositories import audit as audit_repo
from app.repositories import oauth_tokens as tokens_repo
from app.repositories import sync_state as sync_state_repo
from app.security import signed_cookie
from app.security.crypto import KeyringError, get_keyring

logger = get_logger("app.gmail_connect")

ACCOUNT_MISMATCH = "account_mismatch"
NO_REFRESH_TOKEN = "no_refresh_token"  # noqa: S105
SCOPE_DENIED = "scope_denied"
CONNECT_FAILED = "connect_failed"
FLOW_INVALID = "flow_invalid"
SESSION_REQUIRED = "session_required"
ACCESS_DENIED = "access_denied"
GOOGLE_ERROR = "google_error"
FOLLOWUPS_DENIED = "followups_denied"
PUBLIC_CODES = frozenset(
    {
        ACCOUNT_MISMATCH,
        NO_REFRESH_TOKEN,
        SCOPE_DENIED,
        CONNECT_FAILED,
        FLOW_INVALID,
        SESSION_REQUIRED,
        ACCESS_DENIED,
        GOOGLE_ERROR,
        FOLLOWUPS_DENIED,
    }
)


class ConnectFailed(Exception):
    """`code` is stable: it is logged and sent to the frontend as `?gmail_error=`."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Authorization:
    url: str
    cookie_value: str


@dataclass(frozen=True)
class ConnectOutcome:
    followups_denied: bool  # compose was asked for but not granted; read access still works


def begin(
    oidc: GoogleOidc, user: User, followups: bool, settings: Settings, now: datetime
) -> Authorization:
    state, nonce, pkce = random_token(), random_token(), new_pkce()
    url = oidc.build_connect_url(
        state,
        pkce.challenge,
        nonce,
        connect_scopes(followups),
        settings.connect_redirect_uri,
        login_hint=user.email,
    )
    flow = {
        "state": state,
        "verifier": pkce.verifier,
        "nonce": nonce,
        "user_id": str(user.id),
        "followups": followups,
    }
    return Authorization(url, signed_cookie.sign(signed_cookie.CONNECT_KIND, flow, now, settings))


def read_flow(
    raw: str | None, user: User, state: str | None, now: datetime, settings: Settings
) -> dict[str, object]:
    """The verified flow payload, bound to this user and this `state`; else ConnectFailed."""
    flow = (
        signed_cookie.verify(
            signed_cookie.CONNECT_KIND, raw, now, signed_cookie.FLOW_MAX_AGE, settings
        )
        if raw
        else None
    )
    if flow is None or flow.get("user_id") != str(user.id):
        raise ConnectFailed(FLOW_INVALID)
    if not state or not hmac.compare_digest(state.encode(), str(flow.get("state")).encode()):
        raise ConnectFailed(FLOW_INVALID)
    return flow


def complete(
    session: Session,
    user: User,
    oidc: GoogleOidc,
    settings: Settings,
    flow: dict[str, object],
    code: str,
    now: datetime,
) -> ConnectOutcome:
    """Exchange the code and store the token. Does not commit."""
    try:
        token = oidc.exchange_code(code, str(flow["verifier"]), settings.connect_redirect_uri)
        identity = oidc.verify_id_token(token.id_token, str(flow["nonce"]))
    except OidcError as exc:
        logger.warning("gmail_connect.exchange_failed", extra={"error_code": exc.code})
        raise ConnectFailed(CONNECT_FAILED) from None
    if not hmac.compare_digest(identity.sub.encode(), user.google_sub.encode()):
        raise ConnectFailed(ACCOUNT_MISMATCH)
    if token.refresh_token is None:
        raise ConnectFailed(NO_REFRESH_TOKEN)
    if not can_read(token.scope):
        raise ConnectFailed(SCOPE_DENIED)
    _store(session, user.id, token.refresh_token, token.scope, now)
    return ConnectOutcome(
        followups_denied=bool(flow.get("followups")) and not can_compose(token.scope)
    )


def _store(
    session: Session, user_id: uuid.UUID, refresh_token: str, scope: str, now: datetime
) -> None:
    before = tokens_repo.active_row(session, user_id)
    had_compose = before is not None and can_compose(before.scopes)
    scopes = " ".join(sorted(parse_scopes(scope)))
    try:
        tokens_repo.save_refresh_token(session, user_id, refresh_token, scopes, get_keyring())
    except KeyringError:
        logger.error("gmail_connect.keyring_unavailable")
        raise ConnectFailed(CONNECT_FAILED) from None
    sync_state_repo.clear_revoked(session, user_id)
    if before is None:
        audit_repo.record(session, user_id, AuditAction.GMAIL_CONNECTED, now)
    if can_compose(scopes) and not had_compose:
        audit_repo.record(session, user_id, AuditAction.FOLLOWUPS_ENABLED, now)
