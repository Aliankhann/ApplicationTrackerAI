"""Signed digest-unsubscribe tokens: HMAC-SHA256 over (user_id, purpose, issued_at).

The key is derived from the session secret with a purpose label, so a token can never be
confused with, or used to forge, anything else signed with that secret. Verification touches no
database: it is pure signature and expiry arithmetic.
"""

import base64
import hashlib
import hmac
import uuid
from datetime import datetime, timedelta

PURPOSE = "digest_unsubscribe"
MAX_CLOCK_SKEW = timedelta(minutes=5)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _key(secret: str) -> bytes:
    return hmac.new(secret.encode(), f"key:{PURPOSE}".encode(), hashlib.sha256).digest()


def _mac(secret: str, user_id: uuid.UUID, issued: int) -> bytes:
    message = f"{PURPOSE}|{user_id}|{issued}".encode()
    return hmac.new(_key(secret), message, hashlib.sha256).digest()


def create_token(secret: str, user_id: uuid.UUID, now: datetime) -> str:
    issued = int(now.timestamp())
    return f"{user_id.hex}.{issued}.{_b64(_mac(secret, user_id, issued))}"


def verify_token(secret: str, token: str, now: datetime, max_age: timedelta) -> uuid.UUID | None:
    """The user id when the token is authentic and fresh, else None (one indistinguishable case)."""
    try:
        raw_id, raw_issued, raw_mac = token.split(".")
        user_id = uuid.UUID(hex=raw_id)
        issued = int(raw_issued)
        given = _unb64(raw_mac)
    except ValueError:
        return None
    if not hmac.compare_digest(given, _mac(secret, user_id, issued)):
        return None
    age = now - datetime.fromtimestamp(issued, now.tzinfo)  # issued is authentic, hence sane
    return user_id if -MAX_CLOCK_SKEW <= age <= max_age else None
