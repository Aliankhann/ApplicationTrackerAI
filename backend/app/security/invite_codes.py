"""Invite code generation, normalization, and hashing. Codes and hashes are never logged."""

import base64
import hashlib
import secrets
from datetime import datetime

CODE_BYTES = 20  # 160 bits
GROUP_SIZE = 4
CODE_LENGTH = 32  # base32 chars in an unpadded 20-byte code
BASE32_ALPHABET = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")


def generate_code() -> str:
    """Return a new code: 32 base32 chars shown as 8 hyphenated groups of 4."""
    raw = base64.b32encode(secrets.token_bytes(CODE_BYTES)).decode("ascii").rstrip("=")
    return "-".join(raw[i : i + GROUP_SIZE] for i in range(0, len(raw), GROUP_SIZE))


def normalize_code(raw: str) -> str:
    """Uppercase and strip spaces and hyphens."""
    return "".join(raw.split()).replace("-", "").upper()


def is_well_formed(raw: str) -> bool:
    """True if the normalized input has the exact length and alphabet of a generated code."""
    code = normalize_code(raw)
    return len(code) == CODE_LENGTH and set(code) <= BASE32_ALPHABET


def hash_code(code: str) -> str:
    """SHA-256 hex of the normalized code. Deterministic so lookups use the unique index."""
    if not is_well_formed(code):
        raise ValueError("malformed invite code")
    return hashlib.sha256(normalize_code(code).encode("ascii")).hexdigest()


def require_aware(now: datetime) -> datetime:
    """Reject naive datetimes so comparisons against timestamptz columns are always correct."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return now
