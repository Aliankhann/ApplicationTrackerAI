"""Reviewer test: two real sessions run_due for the same user (locks are released per commit)."""

import threading
import time
from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Application, EmailThread, FollowUpTask, Sequence, User
from app.providers.gmail.fake import FakeGmailClient
from app.providers.gmail.types import DraftRef, DraftRequest
from app.services.scheduler import plan_followups, run_due
from tests.test_scheduler import APPLIED, make_app, make_user

NOW = datetime(2026, 3, 9, 14, 30, tzinfo=UTC)  # Mon 10:30 Toronto


class SlowClient(FakeGmailClient):
    def __init__(self, *a: object, **k: object) -> None:
        super().__init__(*a, **k)  # type: ignore[arg-type]
        self.created: list[str] = []

    def create_draft(self, request: DraftRequest) -> DraftRef:
        time.sleep(0.5)
        self.created.append(request.thread_id)
        return super().create_draft(request)


def test_two_workers_never_draft_the_same_thread_twice() -> None:
    engine = create_engine(get_settings().database_url, pool_size=10)
    client = SlowClient("u@example.test", now=NOW)
    with Session(engine) as s:
        user = make_user(s, "America/Toronto")
        for _ in range(4):
            make_app(s, user, client)
        plan_followups(s, user.id, APPLIED)
        s.commit()
        uid = user.id

    def worker(delay: float) -> None:
        time.sleep(delay)
        with Session(engine) as s:
            run_due(s, uid, client, NOW)

    threads = [threading.Thread(target=worker, args=(d,)) for d in (0, 0.7, 1.2)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        dupes = {k: v for k, v in Counter(client.created).items() if v > 1}
        assert not dupes, dupes
    finally:
        with Session(engine) as s:
            apps = s.query(Application.id).filter(Application.user_id == uid)
            s.execute(delete(FollowUpTask).where(FollowUpTask.application_id.in_(apps)))
            s.execute(delete(Application).where(Application.user_id == uid))
            s.execute(delete(EmailThread).where(EmailThread.user_id == uid))
            s.execute(delete(Sequence).where(Sequence.user_id == uid))
            s.execute(delete(User).where(User.id == uid))
            s.commit()
        engine.dispose()
