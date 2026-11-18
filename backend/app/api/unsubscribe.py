"""Public, signed digest unsubscribe. The token is the only authorization (no session, no CSRF).

GET only shows a confirmation form: mail scanners prefetch links, so it must not change state.
POST (form, JSON, or the RFC 8058 one-click body) turns the digest off and is idempotent.
Every failure is the same 400 so a caller learns nothing about why a token was refused.
"""

import json
import uuid
from datetime import timedelta
from html import escape
from typing import Any
from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.api.deps import Config, Db, Now
from app.repositories import users
from app.security.unsubscribe import verify_token

router = APIRouter(tags=["unsubscribe"])
MAX_BODY_BYTES = 4096


def _page(message: str, form: str = "", status: int = 200) -> HTMLResponse:
    head = "<!doctype html><html><head><title>Daily digest</title></head>"
    html = f"{head}<body><p>{message}</p>{form}</body></html>"
    return HTMLResponse(html, status_code=status)


def _invalid() -> HTMLResponse:
    return _page("This link is invalid or has expired.", status=400)


def _verified(token: str | None, config: Config, now: Now) -> uuid.UUID | None:
    if not token:
        return None
    max_age = timedelta(days=config.digest_unsubscribe_days)
    return verify_token(config.session_secret.get_secret_value(), token, now, max_age)


def _field(data: Any) -> str | None:
    token = data.get("token") if isinstance(data, dict) else None
    return token if isinstance(token, str) else None


async def _body_token(request: Request) -> str | None:
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        return None
    if "json" in request.headers.get("content-type", ""):
        try:
            return _field(json.loads(raw))
        except ValueError:
            return None
    values = parse_qs(raw.decode(errors="replace")).get("token")
    return values[0] if values else None


@router.get("/unsubscribe", response_class=HTMLResponse, include_in_schema=False)
def unsubscribe_page(config: Config, now: Now, token: str | None = None) -> HTMLResponse:
    if _verified(token, config, now) is None or token is None:
        return _invalid()
    form = (
        '<form method="post" action="/unsubscribe">'
        f'<input type="hidden" name="token" value="{escape(token, quote=True)}">'
        '<button type="submit">Turn off the daily digest</button></form>'
    )
    return _page("Turn off your daily application digest email?", form)


@router.post("/unsubscribe", response_class=HTMLResponse, include_in_schema=False)
async def unsubscribe(
    request: Request, db: Db, config: Config, now: Now, token: str | None = None
) -> HTMLResponse:
    user_id = _verified(token or await _body_token(request), config, now)
    if user_id is None:
        return _invalid()
    users.set_digest_enabled(db, user_id, False)
    db.commit()
    return _page("You are unsubscribed from the daily digest.")
