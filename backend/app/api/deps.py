"""Auth dependencies: session lookup, current user, CSRF enforcement."""

import hmac
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import User, UserSession
from app.providers.email import EmailSender, NoopEmailSender
from app.providers.google.revoke import TokenRevoker, UnconfiguredTokenRevoker
from app.repositories import users
from app.security import sessions

CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def get_clock() -> Callable[[], datetime]:
    return lambda: datetime.now(UTC)


def get_now(clock: Annotated[Callable[[], datetime], Depends(get_clock)]) -> datetime:
    """The request's current time; tests override get_clock (or this) with a fake."""
    return clock()


def get_token_revoker() -> TokenRevoker:
    """Production wiring; tests override with FakeTokenRevoker. US-31 adds the real one."""
    return UnconfiguredTokenRevoker()


def get_email_sender() -> EmailSender:
    """Production wiring; US-71 adds the real sender."""
    return NoopEmailSender()


Db = Annotated[Session, Depends(get_db)]
Config = Annotated[Settings, Depends(get_settings)]
Clock = Annotated[Callable[[], datetime], Depends(get_clock)]
Now = Annotated[datetime, Depends(get_now)]
RevokerDep = Annotated[TokenRevoker, Depends(get_token_revoker)]
EmailDep = Annotated[EmailSender, Depends(get_email_sender)]


def _unauthenticated() -> HTTPException:
    return HTTPException(status_code=401, detail="not_authenticated")


def current_session(request: Request, db: Db, settings: Config, clock: Clock) -> UserSession:
    raw = request.cookies.get(settings.session_cookie)
    row = sessions.resolve(db, raw, clock(), settings) if raw else None
    if row is None:
        raise _unauthenticated()
    db.commit()
    return row


CurrentSession = Annotated[UserSession, Depends(current_session)]


def current_user(row: CurrentSession, db: Db) -> User:
    user = users.get(db, row.user_id)
    if user is None:
        raise _unauthenticated()
    return user


CurrentUser = Annotated[User, Depends(current_user)]


# (method, route path) pairs that skip session and CSRF checks. Add deliberately, e.g. an OAuth
# callback or signed unsubscribe link.
PUBLIC_ROUTES: frozenset[tuple[str, str]] = frozenset()


def require_csrf(request: Request, db: Db, settings: Config, clock: Clock) -> None:
    """App-wide default-on guard for every non-safe method, including hidden routes.

    Double-submit plus server binding: header, cookie, and the derived token must all match.
    No session gives 401 before CSRF is considered.
    """
    if request.method in SAFE_METHODS:
        return
    route = request.scope.get("route")
    if (request.method, getattr(route, "path", None)) in PUBLIC_ROUTES:
        return
    row = current_session(request, db, settings, clock)
    expected = sessions.derive_csrf_token(row, settings)
    header = request.headers.get(CSRF_HEADER, "")
    cookie = request.cookies.get(settings.csrf_cookie, "")
    if not (_equal(header, expected) and _equal(cookie, expected)):
        raise HTTPException(status_code=403, detail="csrf_failed")


def _equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def set_session_cookies(
    response: Response, raw_token: str, csrf_token: str, settings: Settings
) -> None:
    """Used by sign-in (US-11). Max-Age is the absolute session lifetime."""
    max_age = settings.session_absolute_days * 86400
    _cookie(response, settings.session_cookie, raw_token, max_age, True, settings)
    _cookie(response, settings.csrf_cookie, csrf_token, max_age, False, settings)


def clear_session_cookies(response: Response, settings: Settings) -> None:
    _cookie(response, settings.session_cookie, "", 0, True, settings)
    _cookie(response, settings.csrf_cookie, "", 0, False, settings)


def _cookie(
    response: Response, name: str, value: str, max_age: int, http_only: bool, settings: Settings
) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        path="/",
        domain=settings.cookie_domain,
        secure=settings.environment != "local",
        httponly=http_only,
        samesite="lax",
    )
