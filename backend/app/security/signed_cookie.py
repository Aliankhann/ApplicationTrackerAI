"""HMAC-signed, short-lived cookie values for the sign-in flow.

The OAuth flow (state, PKCE verifier, nonce) and the invite claim live only in these cookies,
so no table is needed. They are HttpOnly and expire after `max_age` seconds. The signing key is
derived from the session secret and bound to the cookie `kind`, so one kind never validates as
another. Single use comes from three layers: the callback clears the cookie, the cookie expires
in minutes, and Google accepts an authorization code only once.
"""

import base64
import hashlib
import hmac
import json
from datetime import datetime
from typing import Any

from app.config import Settings

FLOW_KIND = "oauth-flow"
INVITE_KIND = "invite-claim"
CONNECT_KIND = "connect-flow"
FLOW_MAX_AGE = 600
INVITE_MAX_AGE = 1800


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(kind: str, body: str, settings: Settings) -> str:
    secret = settings.session_secret.get_secret_value().encode()
    key = hmac.new(secret, f"cookie-signing:{kind}".encode(), hashlib.sha256).digest()
    return _b64(hmac.new(key, body.encode("ascii"), hashlib.sha256).digest())


def sign(kind: str, data: dict[str, Any], now: datetime, settings: Settings) -> str:
    payload = {**data, "k": kind, "t": int(now.timestamp())}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_sign(kind, body, settings)}"


def verify(
    kind: str, value: str, now: datetime, max_age: int, settings: Settings
) -> dict[str, Any] | None:
    """Return the payload, or None if malformed, tampered, of another kind, or expired."""
    body, _, signature = value.partition(".")
    if not body or not hmac.compare_digest(
        signature.encode(), _sign(kind, body, settings).encode()
    ):
        return None
    try:
        payload = json.loads(_unb64(body))
    except ValueError:
        return None
    if not isinstance(payload, dict) or payload.get("k") != kind:
        return None
    issued = payload.get("t")
    if not isinstance(issued, int) or not 0 <= now.timestamp() - issued <= max_age:
        return None
    return payload
