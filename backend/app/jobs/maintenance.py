"""Scheduled housekeeping: purge expired rate-limit windows, sessions, and old audit rows, drop
expired invite holds, and delete invited users who never finished setup within their claim.

Run with `python -m app.jobs.maintenance`, or as the once-a-UTC-day part of the cron tick.
"""

import sys
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.log import get_logger
from app.repositories import invite_codes, job_runs
from app.repositories.audit import purge_audit
from app.security import ratelimit, sessions
from app.services import account

logger = get_logger("app.maintenance")


def _release_invites(session: Session, now: datetime) -> dict[str, int]:
    invite_codes.lock_user_cap(session)  # serialize with sign-ups that claim or count slots
    return {
        "invite_holds": invite_codes.clear_expired_holds(session, now),
        "pending_users": account.delete_expired_pending(session, now),
    }


def run(session: Session, now: datetime) -> dict[str, int]:
    counts = {
        **_release_invites(session, now),
        "rate_limits": ratelimit.purge_old(session, now),
        "sessions": sessions.purge_expired(session, now),
        "audit": purge_audit(session, now),
    }
    session.commit()
    return counts


def run_daily(session: Session, now: datetime) -> bool:
    """Purge unless it already ran on this UTC day; True when it ran. The claim and the purge
    commit together, so a failed purge is retried by the next tick."""
    if not job_runs.claim_daily(session, "maintenance", now):
        session.rollback()
        return False
    run(session, now)
    return True


def main() -> int:
    with SessionLocal() as session:
        counts = run(session, datetime.now(UTC))
    logger.info("maintenance.purged", extra={"count": sum(counts.values())})
    return 0


if __name__ == "__main__":
    sys.exit(main())
