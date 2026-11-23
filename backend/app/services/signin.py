"""The invite gate (US-12): decide whether a verified Google identity may sign in or sign up.

Sign in never needs or uses a code. Sign up (a new person) needs the code this browser holds:
in one transaction (serialized by the user-cap lock) the user is created pending, the code is
claimed for them for `invite_claim_hours`, and the hold is cleared. The code is only consumed when
Gmail is connected (see `account_setup`). Nothing is written for a rejected person: the caller
commits only after the session exists, and rolls back on `SignInRejected`.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.log import get_logger
from app.models import User
from app.providers.google.oidc import Identity
from app.repositories import invite_codes, users
from app.services import account

logger = get_logger("app.signin")

NOT_INVITED = "not_invited"
INVITE_IN_USE = "invite_in_use"
NO_ACCOUNT = "no_account"
ACCOUNT_DISABLED = "account_disabled"
SIGN_IN_FAILED = "sign_in_failed"
SIGN_UP = "signup"
SIGN_IN = "signin"


class SignInRejected(Exception):
    """`code` is stable: it goes to the log and, as `?error=`, to the sign-in page."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def admit(
    session: Session,
    identity: Identity,
    mode: str,
    invite: tuple[uuid.UUID, str] | None,
    settings: Settings,
    now: datetime,
) -> User:
    """Return the user to sign in, creating them when the gate allows. Does not commit.

    `invite` is (invite id, hold token) from the browser's invite cookie.
    """
    existing = users.get_by_google_sub(session, identity.sub)
    if existing is not None:
        if existing.disabled_at is not None:
            raise SignInRejected(ACCOUNT_DISABLED)
        _sync_email(existing, identity.email.lower())
        return existing
    email = identity.email.lower()
    allowlisted = email in settings.allowlist
    if mode != SIGN_UP and not allowlisted:
        raise SignInRejected(NO_ACCOUNT)
    invite_codes.lock_user_cap(session)  # before counting slots, so the cap cannot be overshot
    if not allowlisted:
        account.delete_expired_pending(session, now)  # free claims that lapsed
    if invite_codes.slots_in_use(session, now) >= settings.max_users:
        raise SignInRejected(NOT_INVITED)
    try:
        with session.begin_nested():
            if allowlisted:
                return users.create(session, identity.sub, email, setup_completed_at=now)
            return _create_pending(session, identity.sub, email, invite, settings, now)
    except IntegrityError as exc:
        raise SignInRejected(SIGN_IN_FAILED) from exc


def _sync_email(user: User, email: str) -> None:
    if user.email != email:
        user.email = email
        logger.info("auth.email_updated")


def _create_pending(
    session: Session,
    google_sub: str,
    email: str,
    invite: tuple[uuid.UUID, str] | None,
    settings: Settings,
    now: datetime,
) -> User:
    if invite is None:
        raise SignInRejected(NOT_INVITED)
    invite_id, token = invite
    row = invite_codes.get_unspent(session, invite_id, now)
    if row is None:
        raise SignInRejected(NOT_INVITED)
    target = row.created_for_email
    if target is not None and target.lower() != email:
        raise SignInRejected(NOT_INVITED)
    user = users.create(session, google_sub, email, setup_completed_at=None)
    claim_for = timedelta(hours=settings.invite_claim_hours)
    if not invite_codes.claim(session, invite_id, token, user.id, now, claim_for):
        raise SignInRejected(INVITE_IN_USE)  # someone else holds or claimed it, or the hold lapsed
    return user
