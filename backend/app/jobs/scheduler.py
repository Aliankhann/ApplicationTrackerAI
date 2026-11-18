"""Follow-up scheduler job: plan steps and draft the due ones, for users who allowed drafts.

Run with `python -m app.jobs.scheduler`. Only users whose token has `gmail.compose` are
visited; a failure for one user never stops the rest. Drafts only, never sends. Logs counts only.
"""

import sys
import uuid
from collections import Counter
from collections.abc import Collection
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.log import get_logger
from app.providers.gmail.errors import GmailAuthRevoked
from app.providers.google.scopes import can_compose
from app.repositories import oauth_tokens as tokens_repo
from app.security.crypto import DecryptionError, KeyringError
from app.services.gmail_access import ClientFactory, gmail_client_for
from app.services.scheduler import plan_followups, run_due

logger = get_logger("app.jobs.scheduler")


def run(
    session: Session,
    now: datetime,
    client_factory: ClientFactory,
    only: Collection[uuid.UUID] | None = None,
) -> Counter[str]:
    """Returns counts: users, drafted, skipped (no compose scope), failed. `only` limits users."""
    counts: Counter[str] = Counter()
    for user_id, scopes in tokens_repo.active_scopes(session):
        if only is not None and user_id not in only:
            continue
        if not can_compose(scopes):
            counts["skipped"] += 1
            continue
        try:
            plan_followups(session, user_id, now)
            session.commit()
            client = client_factory(session, user_id)
            counts["drafted"] += run_due(session, user_id, client, now).drafted
            counts["users"] += 1
        except (GmailAuthRevoked, DecryptionError, KeyringError) as exc:
            session.rollback()
            logger.warning("scheduler.user_failed", extra={"error_code": type(exc).__name__})
            counts["failed"] += 1
        except Exception as exc:  # contain anything unexpected so the next user still runs
            session.rollback()
            logger.warning("scheduler.user_failed", extra={"exc_type": type(exc).__name__})
            counts["failed"] += 1
    return counts


def main() -> int:
    with SessionLocal() as session:
        counts = run(session, datetime.now(UTC), gmail_client_for)
    logger.info(
        "scheduler.job_finished",
        extra={
            "job": "scheduler",
            "count": counts["drafted"],
            "skipped": counts["skipped"],
            "failed": counts["failed"],
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
