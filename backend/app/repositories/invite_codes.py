"""Invite code persistence. Codes are only ever stored as hashes."""

import hashlib
import uuid
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, cast

from sqlalchemy import ColumnElement, CursorResult, and_, func, or_, select, text, update
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


class HoldResult(StrEnum):
    HELD = "held"
    IN_USE = "in_use"  # held by another browser, or claimed by a user still setting up
    UNAVAILABLE = "unavailable"  # unknown, used, expired, revoked


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def find_by_code(session: Session, code: str) -> InviteCode | None:
    """The invite for `code` in any state. Malformed input never matches."""
    if not is_well_formed(code):
        return None
    stmt = select(InviteCode).where(InviteCode.code_hash == hash_code(code))
    return session.scalars(stmt).one_or_none()


def _is_open(now: datetime) -> ColumnElement[bool]:
    """Not used, revoked, or expired, and not claimed by a user with an unexpired claim."""
    return and_(
        InviteCode.used_at.is_(None),
        InviteCode.revoked_at.is_(None),
        InviteCode.expires_at > now,
        or_(InviteCode.claimed_by_user_id.is_(None), InviteCode.claimed_until <= now),
    )


def try_hold(
    session: Session, invite_id: uuid.UUID, token: str, now: datetime, hold_for: timedelta
) -> HoldResult:
    """Atomically hold an available code for the browser that owns `token`.

    The same token refreshes its own hold; a different token wins only after the hold expired.
    """
    require_aware(now)
    digest = hash_token(token)
    stmt = (
        update(InviteCode)
        .where(
            InviteCode.id == invite_id,
            _is_open(now),
            or_(
                InviteCode.hold_token_hash.is_(None),
                InviteCode.held_until <= now,
                InviteCode.hold_token_hash == digest,
            ),
        )
        .values(held_until=now + hold_for, hold_token_hash=digest)
        .execution_options(synchronize_session=False)
    )
    if cast(CursorResult[Any], session.execute(stmt)).rowcount == 1:
        return HoldResult.HELD
    invite = session.get(InviteCode, invite_id, populate_existing=True)
    if invite is None or invite.used_at or invite.revoked_at or invite.expires_at <= now:
        return HoldResult.UNAVAILABLE
    return HoldResult.IN_USE


def get_unspent(session: Session, invite_id: uuid.UUID, now: datetime) -> InviteCode | None:
    """The invite by id unless used, revoked, or expired (whoever holds or claims it)."""
    require_aware(now)
    stmt = select(InviteCode).where(
        InviteCode.id == invite_id,
        InviteCode.used_at.is_(None),
        InviteCode.revoked_at.is_(None),
        InviteCode.expires_at > now,
    )
    return session.scalars(stmt).one_or_none()


def claim(
    session: Session,
    invite_id: uuid.UUID,
    token: str,
    user_id: uuid.UUID,
    now: datetime,
    claim_for: timedelta,
) -> bool:
    """Bind the code to a new user, only if this token still holds it. True for the one winner."""
    require_aware(now)
    stmt = (
        update(InviteCode)
        .where(
            InviteCode.id == invite_id,
            InviteCode.hold_token_hash == hash_token(token),
            InviteCode.held_until > now,
            _is_open(now),
        )
        .values(
            claimed_by_user_id=user_id,
            claimed_until=now + claim_for,
            held_until=None,
            hold_token_hash=None,
        )
        .execution_options(synchronize_session=False)
    )
    return cast(CursorResult[Any], session.execute(stmt)).rowcount == 1


def claim_of(session: Session, user_id: uuid.UUID) -> InviteCode | None:
    stmt = select(InviteCode).where(InviteCode.claimed_by_user_id == user_id)
    return session.scalars(stmt).first()


def finalize(session: Session, user_id: uuid.UUID, now: datetime) -> bool:
    """Make the code used by its claimant. A lapsed claim still counts while the code is valid."""
    require_aware(now)
    stmt = (
        update(InviteCode)
        .where(
            InviteCode.claimed_by_user_id == user_id,
            InviteCode.used_at.is_(None),
            InviteCode.revoked_at.is_(None),
            or_(InviteCode.claimed_until > now, InviteCode.expires_at > now),
        )
        .values(
            used_at=now,
            used_by_user_id=user_id,
            claimed_by_user_id=None,
            claimed_until=None,
            held_until=None,
            hold_token_hash=None,
        )
        .execution_options(synchronize_session=False)
    )
    return cast(CursorResult[Any], session.execute(stmt)).rowcount == 1


def expired_pending_user_ids(session: Session, now: datetime) -> list[uuid.UUID]:
    """Users who signed up with a code, never finished, and whose claim has lapsed."""
    stmt = (
        select(User.id)
        .join(InviteCode, InviteCode.claimed_by_user_id == User.id)
        .where(User.setup_completed_at.is_(None), InviteCode.claimed_until <= require_aware(now))
    )
    return list(session.scalars(stmt))


def clear_expired_holds(session: Session, now: datetime) -> int:
    stmt = (
        update(InviteCode)
        .where(InviteCode.held_until <= require_aware(now))
        .values(held_until=None, hold_token_hash=None)
        .execution_options(synchronize_session=False)
    )
    return cast(CursorResult[Any], session.execute(stmt)).rowcount


def revoke(session: Session, invite_id: uuid.UUID, now: datetime) -> bool:
    """Mark revoked (idempotent: an already revoked or used code is left alone). True if changed."""
    stmt = (
        update(InviteCode)
        .where(
            InviteCode.id == invite_id,
            InviteCode.revoked_at.is_(None),
            InviteCode.used_at.is_(None),
        )
        .values(revoked_at=require_aware(now), held_until=None, hold_token_hash=None)
        .execution_options(synchronize_session=False)
    )
    return cast(CursorResult[Any], session.execute(stmt)).rowcount == 1


def list_all(session: Session) -> list[InviteCode]:
    return list(session.scalars(select(InviteCode).order_by(InviteCode.created_at)))


def state_of(invite: InviteCode, now: datetime) -> str:
    """One of used, revoked, expired, claimed, held, available."""
    if invite.used_at is not None:
        return "used"
    if invite.revoked_at is not None:
        return "revoked"
    if invite.expires_at <= now:
        return "expired"
    if invite.claimed_by_user_id is not None and (invite.claimed_until or now) > now:
        return "claimed"
    if invite.held_until is not None and invite.held_until > now:
        return "held"
    return "available"


USER_CAP_LOCK_KEY = 0x5452_4B52_4341_5001  # fixed 64-bit key: "user cap"


def lock_user_cap(session: Session) -> None:
    """Serialize everything that counts or adds slots; released on commit or rollback."""
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": USER_CAP_LOCK_KEY})


def slots_in_use(session: Session, now: datetime) -> int:
    """Count slots toward the user cap.

    Used codes (even if the user was later deleted, as Google counts every account that ever
    signed in) + codes with an unexpired claim + users not referenced by any code (allowlisted
    users). Holds and unclaimed codes do not count. A pending user whose claim lapsed no longer
    counts. A deleted allowlisted user is not counted (accepted edge case).
    """
    require_aware(now)
    used = InviteCode.used_at.is_not(None)
    claimed = InviteCode.used_at.is_(None) & (InviteCode.claimed_until > now)
    codes = session.scalar(select(func.count()).select_from(InviteCode).where(used | claimed))
    users = session.scalar(
        select(func.count())
        .select_from(User)
        .where(
            User.id.not_in(
                select(InviteCode.used_by_user_id).where(InviteCode.used_by_user_id.is_not(None))
            ),
            User.id.not_in(
                select(InviteCode.claimed_by_user_id).where(
                    InviteCode.claimed_by_user_id.is_not(None)
                )
            ),
        )
    )
    return (codes or 0) + (users or 0)


def forget_user(session: Session, user_id: uuid.UUID, email: str | None) -> None:
    """Drop personal data from invites this user redeemed or that were made for their email.

    Rows are kept (a redeemed one is still a used slot); only the email is removed.

    Google counts every account that ever signed in, so the row (and `used_at`) must stay for
    the 100-user cap; only the email is removed.
    """
    release_claim(session, user_id)
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


def release_claim(session: Session, user_id: uuid.UUID) -> None:
    """Reopen a code claimed by this user; hold and email binding are left as they were."""
    session.execute(
        update(InviteCode)
        .where(InviteCode.claimed_by_user_id == user_id)
        .values(claimed_by_user_id=None, claimed_until=None)
        .execution_options(synchronize_session="fetch")
    )
