"""Reviewer test: several real connections race the lease claim."""

import threading
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import create_engine, delete
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import SyncState, User
from app.services import sync

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


def _race(engine: Engine, uid: uuid.UUID, n: int) -> list[bool]:
    barrier = threading.Barrier(n)
    wins: list[bool] = []

    def worker() -> None:
        with Session(engine) as s:
            args = cast(
                Any, (s, uid, None, None, NOW, s.commit, lambda _x: None, lambda: NOW, False, None)
            )
            ctx = sync._Context(*args)
            barrier.wait()
            wins.append(sync._claim(ctx) is not None)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return wins


def test_parallel_claims_have_exactly_one_winner() -> None:
    engine = create_engine(get_settings().database_url, pool_size=20)
    with Session(engine) as s:
        user = User(google_sub=uuid.uuid4().hex, email="race@example.test")
        s.add(user)
        s.commit()
        uid = user.id
    try:
        for _ in range(15):
            with Session(engine) as s:
                s.execute(delete(SyncState).where(SyncState.user_id == uid))
                s.commit()
            wins = _race(engine, uid, 8)
            assert sum(wins) == 1, wins
    finally:
        with Session(engine) as s:
            s.execute(delete(SyncState).where(SyncState.user_id == uid))
            s.execute(delete(User).where(User.id == uid))
            s.commit()
        engine.dispose()
