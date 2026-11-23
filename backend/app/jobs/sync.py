"""Gmail sync for every user with a live token (a part of the daily cron tick).

Run on its own with `python -m app.jobs.sync`. Users are synced one after another; a failure
for one user never stops the rest, and a user whose sync lease is held (for instance by a
manual sync) is skipped. Logs counts only.
"""

import sys
import uuid
from collections import Counter
from collections.abc import Callable, Collection
from datetime import UTC, datetime, timedelta

import anthropic
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.log import get_logger
from app.providers.classifier.base import ClassifierProvider
from app.providers.classifier.claude import ClaudeProvider
from app.providers.classifier.router import RoutedClassifier
from app.providers.classifier.rules import RulesProvider
from app.repositories import sync_state as sync_state_repo
from app.services.gmail_access import ClientFactory, gmail_client_for
from app.services.llm_controls import LlmControls
from app.services.sync_runner import SyncOutcome, run_user_sync

logger = get_logger("app.jobs.sync")


def production_classifier() -> ClassifierProvider:
    """Rules only unless the LLM is explicitly enabled and a key exists (kill switch)."""
    settings = get_settings()
    rules = RulesProvider(threshold=settings.classifier_review_threshold)
    if not settings.llm_active:
        return rules
    client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key.get_secret_value(),
        timeout=settings.llm_timeout_seconds,
        max_retries=2,
    )
    llm = ClaudeProvider(
        client,
        settings.llm_model,
        settings.classifier_review_threshold,
        rejection_threshold=settings.llm_rejection_threshold,
        offer_interview_threshold=settings.llm_offer_interview_threshold,
    )
    controls = LlmControls(settings.llm_daily_cap_per_user, settings.llm_monthly_call_budget)
    return RoutedClassifier(rules, llm, controls)


def run(
    session: Session,
    now: datetime,
    client_factory: ClientFactory,
    classifier: ClassifierProvider,
    only: Collection[uuid.UUID] | None = None,
    *,
    min_gap: timedelta = timedelta(0),
    should_stop: Callable[[], bool] = lambda: False,
    deadline: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
) -> Counter[SyncOutcome]:
    """Sync users with a live token not synced within `min_gap`, oldest first (or just `only`).

    `should_stop` is checked before each user and `deadline` stops a user's sync between batches
    (time budget). Returns the outcome counts."""
    outcomes: Counter[SyncOutcome] = Counter()
    for user_id in sync_state_repo.due_for_sync(session, now, min_gap):
        if only is not None and user_id not in only:
            continue
        if should_stop():
            break
        try:
            user_now = clock() if clock else now
            outcome = run_user_sync(
                session,
                user_id,
                user_now,
                client_factory,
                classifier,
                deadline=deadline,
                clock=clock,
            )
            outcomes[outcome] += 1
        except Exception as exc:  # contain anything unexpected so the next user still syncs
            session.rollback()
            logger.warning("sync.job_user_failed", extra={"exc_type": type(exc).__name__})
            outcomes[SyncOutcome.FAILED] += 1
    return outcomes


def main() -> int:
    classifier = production_classifier()
    with SessionLocal() as session:
        outcomes = run(session, datetime.now(UTC), gmail_client_for, classifier)
    if isinstance(classifier, RoutedClassifier):
        logger.info(
            "llm.run_finished",
            extra={"llm_calls": classifier.stats.llm_calls, "count": classifier.stats.total},
        )
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
