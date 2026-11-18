"""Invite code persistence. Codes are only ever stored as hashes."""

import uuid
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, func, or_, select, text, update
from sqlalchemy.orm import Session

from app.models import InviteCode, User
from app.security.invite_codes import hash_code, is_well_formed, require_aware


def create(
    session: Session, code_hash: str, expires_at: datetime, created_for_email: str | None = None
) -> InviteCode:
    invite = InviteCode(
        code_hash=code_hash, expires_at=expires_at, created_for_email=created_for_email
    )
    session.add(invite)
    session.flush()
    return invite


def find_redeemable(session: Session, code: str, now: datetime) -> InviteCode | None:
    """Return the invite for `code` if unused and unexpired. Malformed input never matches."""
    require_aware(now)
    if not is_well_formed(code):
        return None
    stmt = select(InviteCode).where(
        InviteCode.code_hash == hash_code(code),
        InviteCode.used_at.is_(None),
        InviteCode.expires_at > now,
    )
    return session.scalars(stmt).one_or_none()


def get_redeemable(session: Session, invite_id: uuid.UUID, now: datetime) -> InviteCode | None:
    """Return the invite by id if still unused and unexpired (re-check at sign-in time)."""
    require_aware(now)
    stmt = select(InviteCode).where(
        InviteCode.id == invite_id, InviteCode.used_at.is_(None), InviteCode.expires_at > now
    )
    return session.scalars(stmt).one_or_none()


def mark_used(session: Session, invite_id: uuid.UUID, user_id: uuid.UUID, now: datetime) -> bool:
    """Atomically claim an invite. True only for the caller that wins the race."""
    stmt = (
        update(InviteCode)
        .where(InviteCode.id == invite_id, InviteCode.used_at.is_(None))
        .values(used_at=require_aware(now), used_by_user_id=user_id)
    )
    result = cast(CursorResult[Any], session.execute(stmt))
    return result.rowcount == 1


USER_CAP_LOCK_KEY = 0x5452_4B52_4341_5001  # fixed 64-bit key: "user cap"


def lock_user_cap(session: Session) -> None:
    """Serialize everything that counts or adds slots; released on commit or rollback."""
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": USER_CAP_LOCK_KEY})


def slots_in_use(session: Session, now: datetime) -> int:
    """Count slots toward the user cap.

    Used codes (even if the user was later deleted, as Google counts every account that ever
    signed in) + unused unexpired codes + users not referenced by any code (allowlisted users).
    A deleted allowlisted user is not counted (accepted edge case).
    """
    require_aware(now)
    used = InviteCode.used_at.is_not(None)
    pending = InviteCode.used_at.is_(None) & (InviteCode.expires_at > now)
    codes = session.scalar(select(func.count()).select_from(InviteCode).where(used | pending))
    referenced = select(InviteCode.used_by_user_id).where(InviteCode.used_by_user_id.is_not(None))
    users = session.scalar(select(func.count()).select_from(User).where(User.id.not_in(referenced)))
    return (codes or 0) + (users or 0)


def forget_user(session: Session, user_id: uuid.UUID, email: str | None) -> None:
    """Drop personal data from invites this user redeemed or that were made for their email.

    Rows are kept (a redeemed one is still a used slot); only the email is removed.

    Google counts every account that ever signed in, so the row (and `used_at`) must stay for
    the 100-user cap; only the email is removed.
    """
    session.execute(
        update(InviteCode)
        .where(
            or_(
                InviteCode.used_by_user_id == user_id,
                func.lower(InviteCode.created_for_email) == (email or "").lower(),
            )
        )
        .values(created_for_email=None)
        .execution_options(synchronize_session="fetch")
    )
