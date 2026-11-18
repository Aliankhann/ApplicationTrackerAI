"""Review: concurrent admissions near the user cap must not exceed max_users."""

import threading
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import User
from app.providers.google.oidc import Identity
from app.repositories import invite_codes
from app.services import signin


@pytest.mark.xfail(strict=True, reason="no lock between slots_in_use and insert (cap race)")
def test_two_allowlisted_users_cannot_both_take_the_last_slot() -> None:
    engine = create_engine(get_settings().database_url)
    now = datetime.now(UTC)
    tag = uuid.uuid4().hex
    emails = [f"a{tag}@example.test", f"b{tag}@example.test"]
    with Session(engine) as s:
        base = invite_codes.slots_in_use(s, now)
    settings = Settings(
        session_secret=get_settings().session_secret,
        max_users=base + 1,
        allowlist_emails=",".join(emails),
    )
    sessions = [Session(engine), Session(engine)]
    barrier = threading.Barrier(2)
    subs = [f"race-{tag}-{i}" for i in range(2)]

    def go(i: int) -> None:
        try:
            signin.admit(sessions[i], Identity(subs[i], emails[i], True), None, settings, now)
            barrier.wait(timeout=5)  # both counted before either commits
            sessions[i].commit()
        except (signin.SignInRejected, threading.BrokenBarrierError):
            sessions[i].rollback()

    threads = [threading.Thread(target=go, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    try:
        with Session(engine) as s:
            assert invite_codes.slots_in_use(s, now) <= settings.max_users
    finally:
        for s in sessions:
            s.close()
        with Session(engine) as c:
            c.execute(delete(User).where(User.google_sub.in_(subs)))
            c.commit()
        engine.dispose()
