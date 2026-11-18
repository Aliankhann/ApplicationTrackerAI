"""Scheduled housekeeping: purge expired rate-limit windows, sessions, and old audit rows.

Run with `python -m app.jobs.maintenance`; scheduling itself is US-05.
"""

import sys
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.log import get_logger
from app.repositories.audit import purge_audit
from app.security import ratelimit, sessions

logger = get_logger("app.maintenance")


def run(session: Session, now: datetime) -> dict[str, int]:
    counts = {
        "rate_limits": ratelimit.purge_old(session, now),
        "sessions": sessions.purge_expired(session, now),
        "audit": purge_audit(session, now),
    }
    session.commit()
    return counts


def main() -> int:
    with SessionLocal() as session:
        counts = run(session, datetime.now(UTC))
    logger.info("maintenance.purged", extra={"count": sum(counts.values())})
    return 0


if __name__ == "__main__":
    sys.exit(main())
