"""Hourly Gmail sync for every user with a live token.

Run with `python -m app.jobs.sync`. Users are synced one after another; a failure for one user
never stops the rest, and a user whose sync lease is held (for instance by a manual sync) is
skipped. Logs counts only.
"""

import sys
import uuid
from collections import Counter
from collections.abc import Collection
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.log import get_logger
from app.providers.classifier.base import ClassifierProvider
from app.providers.classifier.rules import RulesProvider
from app.repositories import oauth_tokens as tokens_repo
from app.services.gmail_access import ClientFactory, gmail_client_for
from app.services.sync_runner import SyncOutcome, run_user_sync

logger = get_logger("app.jobs.sync")


def production_classifier() -> ClassifierProvider:
    return RulesProvider(threshold=get_settings().classifier_review_threshold)


def run(
    session: Session,
    now: datetime,
    client_factory: ClientFactory,
    classifier: ClassifierProvider,
    only: Collection[uuid.UUID] | None = None,
) -> Counter[SyncOutcome]:
    """Sync every user with a live token (or just `only`); returns the outcome counts."""
    outcomes: Counter[SyncOutcome] = Counter()
    for user_id, _ in tokens_repo.active_scopes(session):
        if only is not None and user_id not in only:
            continue
        try:
            outcomes[run_user_sync(session, user_id, now, client_factory, classifier)] += 1
        except Exception as exc:  # contain anything unexpected so the next user still syncs
            session.rollback()
            logger.warning("sync.job_user_failed", extra={"exc_type": type(exc).__name__})
            outcomes[SyncOutcome.FAILED] += 1
    return outcomes


def sync_user_in_new_session(user_id: uuid.UUID) -> None:
    """Background task for the manual sync route: its own session, the real clock and client."""
    with SessionLocal() as session:
        run_user_sync(
            session, user_id, datetime.now(UTC), gmail_client_for, production_classifier()
        )


def main() -> int:
    with SessionLocal() as session:
        outcomes = run(session, datetime.now(UTC), gmail_client_for, production_classifier())
    logger.info(
        "sync.job_finished",
        extra={
            "job": "sync",
            "count": outcomes[SyncOutcome.COMPLETED],
            "skipped": outcomes[SyncOutcome.ALREADY_RUNNING],
            "failed": outcomes[SyncOutcome.FAILED] + outcomes[SyncOutcome.REVOKED],
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
