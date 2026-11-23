"""Once-a-day job bookkeeping."""

from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import JobRun


def claim_daily(session: Session, job: str, now: datetime) -> bool:
    """True when `job` has not run yet on this UTC day; records the run in the caller's
    transaction, so a failure that rolls back also releases the claim. Concurrent callers
    serialize on the row, and the loser sees the day already claimed."""
    day_start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = (
        insert(JobRun)
        .values(job=job, last_run_at=now)
        .on_conflict_do_update(
            index_elements=["job"], set_={"last_run_at": now}, where=JobRun.last_run_at < day_start
        )
        .returning(JobRun.job)
    )
    return session.execute(stmt).first() is not None
