"""The single daily cron tick: sync, follow-up drafts, digest, maintenance, in one budget.

Vercel Hobby allows one scheduled run a day, so everything periodic runs from here. Order and
budget split (cumulative shares of the usable time, unused time rolls over):

  1. Gmail sync, oldest last_synced_at first, up to 60%. Users not reached are first next time;
     an unfinished initial sync continues on the next run.
  2. Follow-up scheduler (plan + draft) up to 85%.
  3. Digest up to 100%.
  4. Maintenance purge once per UTC day (a few deletes; no budget check).

Each part checks the budget before every user and stops cleanly. Logs counts only.
"""

from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import Settings
from app.jobs import digest as digest_job
from app.jobs import maintenance
from app.jobs import scheduler as scheduler_job
from app.jobs import sync as sync_job
from app.log import get_logger
from app.providers.classifier.base import ClassifierProvider
from app.providers.email import EmailSender
from app.repositories import digest as digest_repo
from app.services.budget import Budget
from app.services.gmail_access import ClientFactory
from app.services.sync_runner import SyncOutcome

logger = get_logger("app.jobs.tick")
SYNC_SHARE = 0.6
FOLLOWUP_SHARE = 0.85
DIGEST_SHARE = 1.0


@dataclass
class TickSummary:
    """Counts only. Safe to log and to return from the cron endpoint."""

    sync_completed: int = 0
    sync_partial: int = 0
    sync_paused: int = 0  # Gmail rate limited; those users continue on the next run
    sync_failed: int = 0
    followups_users: int = 0
    followups_drafted: int = 0
    followups_failed: int = 0
    digest_sent: int = 0
    digest_failed: int = 0
    maintenance_ran: int = 0
    budget_exhausted: bool = False


def _sync(
    session: Session,
    settings: Settings,
    clock: Callable[[], datetime],
    client_factory: ClientFactory,
    classifier: ClassifierProvider,
    budget: Budget,
    summary: TickSummary,
) -> None:
    outcomes = sync_job.run(
        session,
        clock(),
        client_factory,
        classifier,
        min_gap=timedelta(hours=settings.sync_min_gap_hours),
        should_stop=budget.should_stop(SYNC_SHARE),
        deadline=budget.stop_at(SYNC_SHARE),
        clock=clock,
    )
    summary.sync_completed = outcomes[SyncOutcome.COMPLETED]
    summary.sync_partial = outcomes[SyncOutcome.PARTIAL]
    summary.sync_paused = outcomes[SyncOutcome.PAUSED]
    summary.sync_failed = outcomes[SyncOutcome.FAILED] + outcomes[SyncOutcome.REVOKED]
    if summary.sync_partial:  # stopped by the deadline inside a user's sync
        budget.tripped = True


def _followups(
    session: Session,
    clock: Callable[[], datetime],
    client_factory: ClientFactory,
    budget: Budget,
    summary: TickSummary,
) -> None:
    counts: Counter[str] = scheduler_job.run(
        session, clock(), client_factory, should_stop=budget.should_stop(FOLLOWUP_SHARE)
    )
    summary.followups_users = counts["users"]
    summary.followups_drafted = counts["drafted"]
    summary.followups_failed = counts["failed"]


def _digest(
    session: Session,
    settings: Settings,
    clock: Callable[[], datetime],
    sender: EmailSender,
    budget: Budget,
    summary: TickSummary,
) -> None:
    counts = digest_job.run_digest(
        session, sender, clock(), settings, should_stop=budget.should_stop(DIGEST_SHARE)
    )
    summary.digest_sent = counts[digest_repo.SENT]
    summary.digest_failed = counts[digest_repo.FAILED]


def run_tick(
    session: Session,
    settings: Settings,
    clock: Callable[[], datetime],
    client_factory: ClientFactory,
    classifier: ClassifierProvider,
    sender: EmailSender,
) -> TickSummary:
    """One budgeted pass over every part; per-user failures never block the other users."""
    budget = Budget(clock, settings.cron_time_budget_seconds)
    summary = TickSummary()
    _sync(session, settings, clock, client_factory, classifier, budget, summary)
    _followups(session, clock, client_factory, budget, summary)
    _digest(session, settings, clock, sender, budget, summary)
    summary.maintenance_ran = int(maintenance.run_daily(session, clock()))
    summary.budget_exhausted = budget.tripped
    logger.info(
        "cron.tick", extra={"job": "tick", **{k: int(v) for k, v in asdict(summary).items()}}
    )
    return summary
