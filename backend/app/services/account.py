"""Disconnect Gmail and delete an account. Nothing here logs tokens, emails, or content."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.config import Settings
from app.log import get_logger
from app.models import AuditAction, User
from app.providers.google.revoke import RevokeResult, TokenRevoker
from app.repositories import audit as audit_repo
from app.repositories import followups as followups_repo
from app.repositories import invite_codes as invite_codes_repo
from app.repositories import oauth_tokens as tokens_repo
from app.repositories import sync_state as sync_state_repo
from app.repositories import threads as threads_repo
from app.repositories import users as users_repo
from app.security.crypto import DecryptionError, KeyringError, get_keyring
from app.services.followup_policy import StopReason

logger = get_logger("app.account")

ERROR_DECRYPT = "token_decrypt_failed"
ERROR_REVOKE_FAILED = "revoke_failed"


class SyncInProgress(Exception):
    """A sync holds the lease; the caller should retry shortly."""


@dataclass(frozen=True)
class DisconnectResult:
    revoked_at_google: bool | None  # None: there was no live token to revoke


def revoke_at_google(session: Session, user_id: uuid.UUID, revoker: TokenRevoker) -> bool | None:
    """Revoke the user's live refresh token. None: nothing to revoke; False: Google call failed.

    Raises RevokerNotConfigured when no real revoker is wired.
    """
    try:
        token = tokens_repo.load_refresh_token(session, user_id, get_keyring())
    except (DecryptionError, KeyringError):
        logger.warning("account.revoke_skipped", extra={"error_code": ERROR_DECRYPT})
        return False
    if token is None:
        return None
    result = revoker.revoke(token)
    if result is RevokeResult.FAILED:
        logger.warning("account.revoke_failed", extra={"error_code": ERROR_REVOKE_FAILED})
        return False
    return True


def disconnect_gmail(
    session: Session, user_id: uuid.UUID, revoker: TokenRevoker, now: datetime
) -> DisconnectResult:
    """Revoke, delete the token and synced threads, cancel open follow-ups, reset sync state.

    Raises SyncInProgress (nothing changed) or RevokerNotConfigured (nothing changed). A failed
    Google call does not block the local cleanup. Caller commits.
    """
    if sync_state_repo.lease_held(session, user_id, now):
        raise SyncInProgress
    had_token = tokens_repo.get_row(session, user_id) is not None
    revoked = revoke_at_google(session, user_id, revoker)
    tokens_repo.delete_token(session, user_id)
    threads_repo.delete_all(session, user_id)
    followups_repo.cancel_open(session, user_id, StopReason.GMAIL_DISCONNECTED.value)
    sync_state_repo.reset(session, user_id)
    if had_token:
        audit_repo.record(session, user_id, AuditAction.GMAIL_DISCONNECTED, now)
    return DisconnectResult(revoked)


def delete_account(
    session: Session, user_id: uuid.UUID, now: datetime, *, forget_invite_email: bool = True
) -> None:
    """Remove every row of the user in the caller's single transaction; caller commits.

    Foreign-key cascades remove everything owned by the user (sessions, token, sync and
    scheduler state, threads, applications, tasks, sequences); invite codes keep their row with
    the user link and any email for them removed. The user's audit rows (no FK) are deleted
    explicitly, then one
    anonymous `account_deleted` entry is written. A code the user had claimed becomes available
    again. A pending user's deletion (and `forget_invite_email=False`, expiry cleanup) keeps an
    operator-set email binding; a completed user's deletion removes their email from invites.
    """
    audit_repo.delete_for_user(session, user_id)
    user = session.get(User, user_id)
    pending = user is not None and user.setup_completed_at is None
    keep_binding = pending or not forget_invite_email  # a pending user only held a claim
    invite_codes_repo.forget_user(
        session, user_id, user.email if user and not keep_binding else None
    )
    users_repo.delete(session, user_id)
    audit_repo.record(session, None, AuditAction.ACCOUNT_DELETED, now)


def delete_expired_pending(session: Session, now: datetime) -> int:
    """Delete invited users who never connected Gmail before their claim lapsed.

    Each goes through `delete_account`, so every row goes and the code reopens. Allowlisted and
    completed users are never touched. Caller commits; hold the user-cap lock when racing sign-ups.
    """
    expired = invite_codes_repo.expired_pending_user_ids(session, now)
    for user_id in expired:
        delete_account(session, user_id, now, forget_invite_email=False)
    return len(expired)


def complete_setup(session: Session, user: User, settings: Settings, now: datetime) -> bool:
    """Finish a pending user's setup: consume their invite and mark the account complete.

    Called in the transaction that stores the Gmail token. False means the code is gone (revoked,
    or lapsed with no room left): the caller must not store the token. A lapsed claim is
    re-claimed when the code is still valid and a slot is free. A user who is gone (cleanup won the
    race) or has no claim cannot complete without a code; allowlisted and dev users are created
    complete, so they never get here. Caller commits.
    """
    invite_codes_repo.lock_user_cap(session)
    fresh = session.get(User, user.id, populate_existing=True)  # cleanup may have won the race
    if fresh is None:
        return False
    user = fresh
    if user.setup_completed_at is not None:
        return True
    held = invite_codes_repo.claim_of(session, user.id)
    if held is None:
        return False  # pending users always hold a claim; without one there is no code to consume
    lapsed = held.claimed_until is None or held.claimed_until <= now
    if lapsed and invite_codes_repo.slots_in_use(session, now) >= settings.max_users:
        return False
    if not invite_codes_repo.finalize(session, user.id, now):
        return False
    user.setup_completed_at = now
    audit_repo.record(session, user.id, AuditAction.ACCOUNT_SETUP_COMPLETED, now)
    return True
