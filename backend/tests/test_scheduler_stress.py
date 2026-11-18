"""Reviewer stress: 5 workers, 8 tasks, slow drafts, a worker crashing after create_draft."""

import threading
import time
from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Application, EmailThread, FollowUpTask, SchedulerState, Sequence, User
from app.providers.gmail.fake import FakeGmailClient
from app.providers.gmail.types import DraftRef, DraftRequest
from app.services.scheduler import plan_followups, run_due
from tests.test_scheduler import APPLIED, make_app, make_user

NOW = datetime(2026, 3, 9, 14, 30, tzinfo=UTC)  # Mon 10:30 Toronto


class Crash(BaseException):
    pass


class Client(FakeGmailClient):
    crash_first = True

    def __init__(self, *a: object, **k: object) -> None:
        super().__init__(*a, **k)  # type: ignore[arg-type]
        self.created: list[str] = []
        self.lock = threading.Lock()

    def create_draft(self, request: DraftRequest) -> DraftRef:
        time.sleep(0.2)
        with self.lock:
            self.created.append(request.thread_id)
            ref = super().create_draft(request)
            if self.crash_first:
                self.crash_first = False
                raise Crash
            return ref


def test_stress_no_duplicates_cap_holds_and_stale_claim_safe() -> None:
    engine = create_engine(get_settings().database_url, pool_size=20)
    client = Client("u@example.test", now=NOW)
    with Session(engine) as s:
        user = make_user(s, "America/Toronto")
        for _ in range(8):
            make_app(s, user, client)
        plan_followups(s, user.id, APPLIED)
        s.commit()
        uid = user.id

    def worker(delay: float) -> None:
        time.sleep(delay)
        try:
            with Session(engine) as s:
                run_due(s, uid, client, NOW)
        except Crash:
            pass

    try:
        ts = [threading.Thread(target=worker, args=(i * 0.1,)) for i in range(5)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert not {k: v for k, v in Counter(client.created).items() if v > 1}
        assert len(client.created) <= get_settings().followup_daily_draft_cap  # crash draft counts
        # later runs, same day and next days: stale claim must never yield a second draft
        for minutes in (5, 20, 40):
            later = NOW + timedelta(minutes=minutes)
            client.now = later
            with Session(engine) as s:
                run_due(s, uid, client, later)
        dupes = {k: v for k, v in Counter(client.created).items() if v > 1}
        assert not dupes, dupes
        with Session(engine) as s:
            states = Counter(
                s.scalars(
                    select(FollowUpTask.state).join(Application).where(Application.user_id == uid)
                ).all()
            )
        print(states, len(client.created))
        assert states.get("drafting", 0) == 0
    finally:
        with Session(engine) as s:
            apps = s.query(Application.id).filter(Application.user_id == uid)
            s.execute(delete(FollowUpTask).where(FollowUpTask.application_id.in_(apps)))
            s.execute(delete(Application).where(Application.user_id == uid))
            s.execute(delete(EmailThread).where(EmailThread.user_id == uid))
            s.execute(delete(Sequence).where(Sequence.user_id == uid))
            s.execute(delete(SchedulerState).where(SchedulerState.user_id == uid))
            s.execute(delete(User).where(User.id == uid))
            s.commit()
        engine.dispose()
