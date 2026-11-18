"""Database-backed fixed-window rate limits, shared by every instance.

Keys are HMAC-SHA256 of "scope:identifier" under a key derived from the session secret, so raw
IP addresses and user ids are never stored and the table cannot be brute-forced offline.
Counters are committed immediately so a rejected request still counts.
"""

import hashlib
import hmac
from datetime import datetime, timedelta
from typing import Any, cast

from fastapi import Depends, HTTPException, Request
from sqlalchemy import CursorResult, delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.api.deps import Config, Db, Now, SignInRedirect
from app.config import Settings
from app.models import RateLimit

WINDOW = timedelta(hours=1)
RETENTION = timedelta(hours=24)
ERROR_CODE = "rate_limited"


def window_start(now: datetime) -> datetime:
    return now.replace(minute=0, second=0, microsecond=0)


def key_hash(scope: str, identifier: str, settings: Settings) -> str:
    secret = settings.session_secret.get_secret_value().encode()
    key = hmac.new(secret, b"rate-limit-key", hashlib.sha256).digest()
    return hmac.new(key, f"{scope}:{identifier}".encode(), hashlib.sha256).hexdigest()


def hit(session: Session, key: str, now: datetime) -> int:
    """Atomically count one request in the current window and return the new count."""
    insert_stmt = insert(RateLimit).values(key_hash=key, window_start=window_start(now), count=1)
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=[RateLimit.key_hash, RateLimit.window_start],
        set_={"count": RateLimit.count + 1},
    ).returning(RateLimit.count)
    return int(session.execute(stmt).scalar_one())


def retry_after(now: datetime) -> int:
    return max(1, int((window_start(now) + WINDOW - now).total_seconds()))


def enforce(
    session: Session,
    settings: Settings,
    now: datetime,
    scope: str,
    identifier: str,
    limit: int,
    redirect: bool = False,
) -> None:
    """Count a request; raise 429 with Retry-After once `limit` per window is exceeded.

    With `redirect` (browser-navigated routes) the failure is a redirect to the sign-in page.
    """
    count = hit(session, key_hash(scope, identifier, settings), now)
    session.commit()
    if count > limit:
        if redirect:
            raise SignInRedirect(ERROR_CODE)
        raise HTTPException(
            status_code=429,
            detail=ERROR_CODE,
            headers={"Retry-After": str(retry_after(now))},
        )


def client_ip(request: Request, settings: Settings) -> str:
    """The socket address, or the Nth-from-right X-Forwarded-For entry behind trusted proxies."""
    n = settings.trusted_proxy_count
    if n > 0:
        entries = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",")]
        entries = [p for p in entries if p]
        if len(entries) >= n:
            return entries[-n]
    return request.client.host if request.client else "unknown"


def limit_by_ip(
    scope: str, per_ip: int, globally: int | None = None, redirect: bool = False
) -> Any:
    """FastAPI dependency factory:
    `per_ip` requests/hour per client IP; `globally` caps all clients together. The global
    counter only moves for requests the per-IP limit let through, so one client cannot burn it.
    """

    def dependency(request: Request, db: Db, settings: Config, now: Now) -> None:
        enforce(db, settings, now, f"{scope}:ip", client_ip(request, settings), per_ip, redirect)
        if globally is not None:
            enforce(db, settings, now, f"{scope}:global", "all", globally, redirect)

    return Depends(dependency)


def purge_old(session: Session, now: datetime) -> int:
    """Delete windows older than 24 hours; returns how many."""
    stmt = delete(RateLimit).where(RateLimit.window_start < now - RETENTION)
    return cast(CursorResult[Any], session.execute(stmt)).rowcount
