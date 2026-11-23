"""Scheduled purge entry point."""

from datetime import timedelta

from sqlalchemy import select

from app.jobs import maintenance
from app.models import RateLimit
from tests.test_sessions import T0, Env, env  # noqa: F401


def test_ac_maintenance_run_purges_old_rate_limit_windows(env: Env) -> None:  # noqa: F811
    env.db.add_all(
        [
            RateLimit(key_hash="a" * 64, window_start=T0 - timedelta(days=2), count=1),
            RateLimit(key_hash="b" * 64, window_start=T0, count=1),
        ]
    )
    env.db.flush()
    counts = maintenance.run(env.db, T0)
    assert counts["rate_limits"] == 1 and set(counts) == {
        "invite_holds",
        "pending_users",
        "rate_limits",
        "sessions",
        "audit",
    }
    assert env.db.scalars(select(RateLimit.key_hash)).all() == ["b" * 64]
