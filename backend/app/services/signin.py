"""The invite gate (US-12): decide whether a verified Google identity may sign in.

Nothing is written for a rejected person. For a new user the user row and the invite claim are
added in the caller's transaction; the caller commits only after the session exists, and rolls
back on `SignInRejected`.
"""

import uuid
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.log import get_logger
from app.models import InviteCode, User
from app.providers.google.oidc import Identity
from app.repositories import invite_codes, users

logger = get_logger("app.signin")

NOT_INVITED = "not_invited"
ACCOUNT_DISABLED = "account_disabled"
SIGN_IN_FAILED = "sign_in_failed"


class SignInRejected(Exception):
    """`code` is stable: it goes to the log and, as `?error=`, to the sign-in page."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def admit(
    session: Session,
    identity: Identity,
    invite_id: uuid.UUID | None,
    settings: Settings,
    now: datetime,
) -> User:
    """Return the user to sign in, creating them when the gate allows. Does not commit."""
    existing = users.get_by_google_sub(session, identity.sub)
    if existing is not None:
        if existing.disabled_at is not None:
            raise SignInRejected(ACCOUNT_DISABLED)
        _sync_email(existing, identity.email.lower())
        return existing
    email = identity.email.lower()
    invite_codes.lock_user_cap(session)  # before counting slots, so the cap cannot be overshot
    allowlisted = email in settings.allowlist
    invite = None if allowlisted else _usable_invite(session, invite_id, email, now)
    if not allowlisted and invite is None:
        raise SignInRejected(NOT_INVITED)
    if not _has_room(session, invite, settings, now):
        raise SignInRejected(NOT_INVITED)
    return _create_user(session, identity.sub, email, invite, now)


def _sync_email(user: User, email: str) -> None:
    if user.email != email:
        user.email = email
        logger.info("auth.email_updated")


def _usable_invite(
    session: Session, invite_id: uuid.UUID | None, email: str, now: datetime
) -> InviteCode | None:
    if invite_id is None:
        return None
    invite = invite_codes.get_redeemable(session, invite_id, now)
    if invite is None:
        return None
    target = invite.created_for_email
    if target is not None and target.lower() != email:
        return None
    return invite


def _has_room(
    session: Session, invite: InviteCode | None, settings: Settings, now: datetime
) -> bool:
    """A pending invite already counts as a slot; a new allowlisted user needs a free one."""
    in_use = invite_codes.slots_in_use(session, now)
    return in_use <= settings.max_users if invite is not None else in_use < settings.max_users


def _create_user(
    session: Session, google_sub: str, email: str, invite: InviteCode | None, now: datetime
) -> User:
    try:
        with session.begin_nested():
            user = users.create(session, google_sub, email)
            if invite is not None and not invite_codes.mark_used(session, invite.id, user.id, now):
                raise SignInRejected(NOT_INVITED)  # lost the race for the code
    except IntegrityError as exc:
        raise SignInRejected(SIGN_IN_FAILED) from exc
    return user
