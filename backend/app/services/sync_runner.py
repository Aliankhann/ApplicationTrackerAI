"""Run one user's sync end to end (client, lease, errors contained). Shared by the inline
`POST /sync` and the daily job. Logs codes and counts only."""

import time
import uuid
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum

from sqlalchemy.orm import Session

from app.log import get_logger
from app.providers.classifier.base import ClassifierProvider
from app.providers.gmail.errors import GmailAuthRevoked
from app.repositories import oauth_tokens as tokens_repo
from app.security.crypto import DecryptionError, KeyringError
from app.services.gmail_access import ClientFactory
from app.services.sync import (
    SyncAlreadyRunning,
    SyncFailed,
    SyncPartial,
    SyncPaused,
    SyncRevoked,
    SyncUserGone,
    run_sync,
)

logger = get_logger("app.sync_runner")
ERROR_TOKEN_UNREADABLE = "token_unreadable"  # noqa: S105


class SyncOutcome(StrEnum):
    COMPLETED = "completed"
    PARTIAL = "partial"  # stopped at the deadline; the next run continues
    PAUSED = "paused"  # Gmail rate limited; progress kept, the next run continues
    ALREADY_RUNNING = "already_running"
    REVOKED = "revoked"
    FAILED = "failed"
    USER_GONE = "user_gone"


def run_user_sync(
    session: Session,
    user_id: uuid.UUID,
    now: datetime,
    client_factory: ClientFactory,
    classifier: ClassifierProvider,
    *,
    sleep: Callable[[float], None] = time.sleep,
    deadline: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
    ensure_progress: bool = True,
) -> SyncOutcome:
    """Never raises for per-user problems; unexpected errors are logged by class name only."""
    try:
        client = client_factory(session, user_id)
    except GmailAuthRevoked:
        tokens_repo.mark_revoked(session, user_id)
        session.commit()
        return SyncOutcome.REVOKED
    except (DecryptionError, KeyringError):
        logger.warning(
            "sync.failed", extra={"user_id": user_id, "error_code": ERROR_TOKEN_UNREADABLE}
        )
        return SyncOutcome.FAILED
    try:
        result = run_sync(
            session,
            user_id,
            client,
            classifier,
            now,
            sleep=sleep,
            deadline=deadline,
            clock=clock,
            ensure_progress=ensure_progress,
        )
    except SyncRevoked:
        return SyncOutcome.REVOKED
    except SyncFailed:
        return SyncOutcome.FAILED
    except Exception as exc:  # run_sync already recorded internal_error in sync_state
        logger.warning("sync.crashed", extra={"user_id": user_id, "exc_type": type(exc).__name__})
        return SyncOutcome.FAILED
    if isinstance(result, SyncAlreadyRunning):
        return SyncOutcome.ALREADY_RUNNING
    if isinstance(result, SyncPartial):
        return SyncOutcome.PARTIAL
    if isinstance(result, SyncPaused):
        return SyncOutcome.PAUSED
    if isinstance(result, SyncUserGone):
        return SyncOutcome.USER_GONE
    return SyncOutcome.COMPLETED
