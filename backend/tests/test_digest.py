"""US-70 digest content and US-71 digest delivery."""

import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.jobs.digest import run_digest
from app.models import Application, DigestLog, FollowUpTask, StatusEvent, User
from app.providers.classifier.types import Label
from app.providers.email import EmailSendError, FakeEmailSender, OutgoingEmail
from app.repositories import digest as repo
from app.services.classification import ApplicationStatus
from app.services.digest import Digest, Entry, build_digest, clean_company, render_html, render_text
from tests.test_applications_api import make_app
from tests.test_sessions import Env, env  # noqa: F401

NOW = datetime(2026, 1, 15, 14, 0, tzinfo=UTC)  # 09:00 Toronto (EST)
TZ = ZoneInfo("America/Toronto")
SUBJECT = "SecretSubjectLine"
SNIPPET = "SecretSnippetText"


def new_user(db: Session, tz: str | None = None, email: str | None = None) -> User:
    user = User(
        google_sub=uuid.uuid4().hex,
        email=email or f"{uuid.uuid4().hex[:8]}@example.test",
        timezone=tz,
    )
    db.add(user)
    db.flush()
    return user


def seed(env: Env, user: User, *, now: datetime = NOW) -> None:  # noqa: F811
    """One of every section, all inside the last 24 hours except the awaiting one."""
    recent = now - timedelta(hours=2)

    def application(
        label: Label, company: str, *, from_user: bool = False, activity: datetime | None = None
    ) -> Application:
        return make_app(
            env,
            user,
            label=label,
            company=company,
            subject=SUBJECT,
            snippet=SNIPPET,
            from_user=from_user,
            activity=activity,
        )

    drafted = application(
        Label.CONFIRMATION, "DraftCo", from_user=True, activity=now - timedelta(days=2)
    )
    env.db.add(
        FollowUpTask(
            application_id=drafted.id, step_index=0, due_at=now, state="drafted", drafted_at=now
        )
    )
    application(Label.CONFIRMATION, "ReplyCo", activity=recent)
    application(Label.REJECTION, "RejectCo", activity=recent)
    application(Label.INTERVIEW, "InterviewCo", activity=recent)
    application(Label.CONFIRMATION, "QuietCo", from_user=True, activity=now - timedelta(days=10))
    env.db.flush()


def build(env: Env, user: User, now: datetime = NOW) -> Digest | None:  # noqa: F811
    return build_digest(env.db, user.id, now - timedelta(hours=24), now, TZ)


def companies(items: tuple[Entry, ...]) -> list[str]:
    return [i.company for i in items]


def test_us70_each_section_is_populated_from_fixtures(env: Env) -> None:  # noqa: F811
    user = new_user(env.db)
    seed(env, user)
    digest = build(env, user)
    assert digest is not None
    assert companies(digest.drafts) == ["DraftCo"]
    assert companies(digest.replies) == ["ReplyCo"]
    assert companies(digest.rejections) == ["RejectCo"]
    assert companies(digest.interviews) == ["InterviewCo"]
    assert companies(digest.awaiting) == ["QuietCo"]
    assert digest.rejections[0].status == "Rejected"
    assert digest.subject == (
        "Your application update: 1 draft, 1 reply, 1 interview update, 1 rejection, "
        "1 awaiting a reply"
    )


def test_us70_waiting_section_skips_applications_older_than_60_days_or_newer_than_7(
    env: Env,  # noqa: F811
) -> None:
    user = new_user(env.db)
    for company, days in (("Fresh", 6), ("Edge", 8), ("Ancient", 61)):
        make_app(env, user, company=company, from_user=True, activity=NOW - timedelta(days=days))
    digest = build(env, user)
    assert digest is not None and companies(digest.awaiting) == ["Edge"]


def test_us70_manual_status_changes_are_not_reported(env: Env) -> None:  # noqa: F811
    user = new_user(env.db)
    application = make_app(
        env, user, company="Mine", from_user=True, activity=NOW - timedelta(days=3)
    )
    env.db.add(
        StatusEvent(
            application_id=application.id,
            from_status=ApplicationStatus.APPLIED,
            to_status=ApplicationStatus.REJECTED,
            reason="manual",
            at=NOW - timedelta(hours=1),
        )
    )
    env.db.flush()
    assert build(env, user) is None


def test_us70_an_empty_day_returns_none(env: Env) -> None:  # noqa: F811
    user = new_user(env.db)
    assert build(env, user) is None
    make_app(env, user, company="Old", activity=NOW - timedelta(days=3))
    assert build(env, user) is None


def test_us70_other_users_data_never_appears(env: Env) -> None:  # noqa: F811
    seed(env, new_user(env.db))
    assert build(env, new_user(env.db)) is None


def test_us70_no_subject_or_snippet_text_in_either_part(env: Env) -> None:  # noqa: F811
    user = new_user(env.db, email="owner.address@example.test")
    seed(env, user)
    digest = build(env, user)
    assert digest is not None
    url = "https://api.example.test/unsubscribe?token=abc"
    for part in (digest.subject, render_text(digest, url), render_html(digest, url)):
        for secret in (SUBJECT, SNIPPET, "owner.address", "acme.example", "jobs@"):
            assert secret not in part


def test_us70_company_is_cleaned_and_html_escaped_and_unknown_gets_a_label(
    env: Env,  # noqa: F811
) -> None:
    user = new_user(env.db)
    make_app(env, user, label=Label.REJECTION, company="<b>Evil</b>‮​", activity=NOW)
    make_app(env, user, label=Label.REJECTION, company=None, activity=NOW)
    digest = build(env, user)
    assert digest is not None
    assert companies(digest.rejections) == ["<b>Evil</b>", "Unknown company"]
    html = render_html(digest, "https://api.example.test/u?token=a&b=<x>")
    assert "<b>Evil</b>" not in html and "&lt;b&gt;Evil&lt;/b&gt;" in html
    assert "‮" not in html and "​" not in html
    assert "token=a&amp;b=&lt;x&gt;" in html
    assert "<b>Evil</b> (Rejected)" in render_text(digest, "u")


def test_us70_long_sections_are_capped_but_counted(env: Env) -> None:  # noqa: F811
    user = new_user(env.db)
    for i in range(12):
        make_app(env, user, label=Label.REJECTION, company=f"Co{i}", activity=NOW)
    digest = build(env, user)
    assert digest is not None
    text_part = render_text(digest, "u")
    assert "Rejections (12)" in text_part and "and 2 more" in text_part and "Co11" not in text_part


# ---------- US-71 delivery ----------


def rows(env: Env, user: User) -> list[DigestLog]:  # noqa: F811
    env.db.expire_all()
    return list(env.db.scalars(select(DigestLog).where(DigestLog.user_id == user.id)))


def mine(sender: FakeEmailSender, user: User) -> list[OutgoingEmail]:
    return [m for m in sender.sent if m.to_address == user.email]


def test_us71_sends_once_with_unsubscribe_headers_and_logs_sent(env: Env) -> None:  # noqa: F811
    user = new_user(env.db, "America/Toronto")
    seed(env, user)
    sender = FakeEmailSender()
    run_digest(env.db, sender, NOW)
    run_digest(env.db, sender, NOW + timedelta(minutes=5))
    (message,) = mine(sender, user)
    headers = message.headers
    assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    link = headers["List-Unsubscribe"]
    assert link.startswith("<http") and link.endswith(">") and "/unsubscribe?token=" in link
    assert link[1:-1] in message.text and link[1:-1].replace("&", "&amp;") in message.html
    (row,) = rows(env, user)
    assert (row.status, row.attempts, row.sent_at, str(row.digest_date)) == (
        "sent",
        1,
        NOW,
        "2026-01-15",
    )


def test_us71_empty_day_sends_nothing_and_records_skipped_empty(env: Env) -> None:  # noqa: F811
    user = new_user(env.db, "America/Toronto")
    sender = FakeEmailSender()
    run_digest(env.db, sender, NOW)
    run_digest(env.db, sender, NOW + timedelta(hours=1))
    assert mine(sender, user) == []
    (row,) = rows(env, user)
    assert row.status == "skipped_empty" and row.sent_at is None


def test_us71_before_8am_local_nothing_happens_and_disabled_users_are_skipped(
    env: Env,  # noqa: F811
) -> None:
    early = new_user(env.db, "America/Toronto")
    off = new_user(env.db, "America/Toronto")
    off.digest_enabled = False
    seed(env, early)
    seed(env, off)
    sender = FakeEmailSender()
    run_digest(env.db, sender, datetime(2026, 1, 15, 12, 59, tzinfo=UTC))  # 07:59 Toronto
    assert rows(env, early) == []
    run_digest(env.db, sender, NOW)
    assert len(mine(sender, early)) == 1 and mine(sender, off) == [] and rows(env, off) == []


def test_us71_timezone_tokyo_user_gets_theirs_after_8_tokyo_not_utc(env: Env) -> None:  # noqa: F811
    tokyo = new_user(env.db, "Asia/Tokyo")
    utc = new_user(env.db, "UTC")
    for user in (tokyo, utc):
        seed(env, user, now=datetime(2026, 1, 15, 0, 30, tzinfo=UTC))
    sender = FakeEmailSender()
    run_digest(env.db, sender, datetime(2026, 1, 14, 22, 30, tzinfo=UTC))  # 07:30 Tokyo
    assert mine(sender, tokyo) == []
    assert len(mine(sender, utc)) == 1  # 22:30 UTC is past 08:00 UTC on Jan 14
    morning = datetime(2026, 1, 15, 0, 30, tzinfo=UTC)  # 09:30 Tokyo, 00:30 UTC
    run_digest(env.db, sender, morning)
    assert len(mine(sender, tokyo)) == 1 and len(mine(sender, utc)) == 1
    assert str(rows(env, tokyo)[0].digest_date) == "2026-01-15"
    run_digest(env.db, sender, morning.replace(hour=8, minute=0))  # 08:00 UTC
    assert len(mine(sender, utc)) == 2 and len(mine(sender, tokyo)) == 1


def test_us71_user_without_timezone_uses_the_default(env: Env) -> None:  # noqa: F811
    user = new_user(env.db, None)
    seed(env, user)
    sender = FakeEmailSender()
    run_digest(env.db, sender, datetime(2026, 1, 15, 12, 30, tzinfo=UTC))  # 07:30 Toronto
    assert mine(sender, user) == []
    run_digest(env.db, sender, NOW)
    assert len(mine(sender, user)) == 1


def test_us71_since_is_the_previous_sent_digest(env: Env) -> None:  # noqa: F811
    user = new_user(env.db, "America/Toronto")
    make_app(
        env, user, label=Label.REJECTION, company="Early", activity=NOW - timedelta(days=2, hours=1)
    )
    env.db.add(
        DigestLog(
            user_id=user.id,
            digest_date=(NOW - timedelta(days=2)).date(),
            status="sent",
            claimed_at=NOW - timedelta(days=2),
            sent_at=NOW - timedelta(days=2),
        )
    )
    make_app(
        env,
        user,
        label=Label.REJECTION,
        company="Later",
        activity=NOW - timedelta(days=1, hours=20),
    )
    sender = FakeEmailSender()
    run_digest(env.db, sender, NOW)
    (message,) = mine(sender, user)
    assert "Later" in message.text and "Early" not in message.text


def test_us71_failure_is_retried_once_on_a_later_run_then_stops(
    env: Env,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    user = new_user(env.db, "America/Toronto", email="private.person@example.test")
    seed(env, user)
    sender = FakeEmailSender()
    sender.fail_with = EmailSendError("provider_5xx")
    with caplog.at_level("INFO"):
        run_digest(env.db, sender, NOW)
    (row,) = rows(env, user)
    assert (row.status, row.attempts) == ("failed", 1)
    run_digest(env.db, sender, NOW + timedelta(minutes=10))  # retry also fails
    assert (rows(env, user)[0].status, rows(env, user)[0].attempts) == ("failed", 2)
    sender.fail_with = None
    run_digest(env.db, sender, NOW + timedelta(minutes=20))  # no third attempt
    assert mine(sender, user) == [] and rows(env, user)[0].attempts == 2
    logged = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "provider_5xx" in logged
    for secret in ("private.person", "DraftCo", SUBJECT, SNIPPET):
        assert secret not in logged


def test_us71_a_failed_first_attempt_succeeds_on_retry_and_sends_once(env: Env) -> None:  # noqa: F811
    user = new_user(env.db, "America/Toronto")
    seed(env, user)
    sender = FakeEmailSender()
    sender.fail_with = EmailSendError()
    run_digest(env.db, sender, NOW)
    sender.fail_with = None
    run_digest(env.db, sender, NOW + timedelta(minutes=10))
    run_digest(env.db, sender, NOW + timedelta(minutes=20))
    assert len(mine(sender, user)) == 1
    assert (rows(env, user)[0].status, rows(env, user)[0].attempts) == ("sent", 2)


def test_us71_unexpected_error_marks_failed_without_leaking_its_text(
    env: Env,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    user = new_user(env.db, "America/Toronto")
    seed(env, user)

    class Exploding(FakeEmailSender):
        def send(self, message: OutgoingEmail) -> None:
            raise RuntimeError("body leaked: " + message.text)

    with caplog.at_level("INFO"):
        run_digest(env.db, Exploding(), NOW)
    assert rows(env, user)[0].status == "failed"
    assert "DraftCo" not in " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)


def test_us71_stale_sending_row_is_never_resent(env: Env) -> None:  # noqa: F811
    user = new_user(env.db, "America/Toronto")
    seed(env, user)
    env.db.add(
        DigestLog(
            user_id=user.id,
            digest_date=NOW.date(),
            status="sending",
            attempts=1,
            claimed_at=NOW - timedelta(minutes=16),
        )
    )
    env.db.flush()
    sender = FakeEmailSender()
    run_digest(env.db, sender, NOW)
    run_digest(env.db, sender, NOW + timedelta(hours=1))
    assert mine(sender, user) == []
    assert (rows(env, user)[0].status, rows(env, user)[0].attempts) == ("failed", repo.MAX_ATTEMPTS)


def test_us71_fresh_sending_row_is_left_alone(env: Env) -> None:  # noqa: F811
    user = new_user(env.db, "America/Toronto")
    seed(env, user)
    env.db.add(
        DigestLog(
            user_id=user.id,
            digest_date=NOW.date(),
            status="sending",
            attempts=1,
            claimed_at=NOW - timedelta(minutes=5),
        )
    )
    env.db.flush()
    sender = FakeEmailSender()
    run_digest(env.db, sender, NOW)
    assert mine(sender, user) == [] and rows(env, user)[0].status == "sending"


def test_us71_two_concurrent_runs_send_exactly_once() -> None:
    engine = create_engine(get_settings().database_url, pool_size=5)
    email = f"race-{uuid.uuid4().hex[:8]}@example.test"

    class Slow(FakeEmailSender):
        def send(self, message: OutgoingEmail) -> None:
            time.sleep(0.5)
            super().send(message)

    sender = Slow()
    with Session(engine) as s:
        user = new_user(s, "America/Toronto", email)
        application = Application(
            user_id=user.id,
            company="RaceCo",
            status=ApplicationStatus.REJECTED,
            last_activity_at=NOW - timedelta(hours=1),
        )
        s.add(application)
        s.flush()
        s.add(
            StatusEvent(
                application_id=application.id,
                to_status=ApplicationStatus.REJECTED,
                reason="created",
                at=NOW - timedelta(hours=1),
            )
        )
        s.commit()
        uid = user.id

    def worker() -> None:
        with Session(engine) as s:
            run_digest(s, sender, NOW)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert [m.to_address for m in sender.sent].count(email) == 1
        with Session(engine) as s:
            assert s.scalars(select(DigestLog.status).where(DigestLog.user_id == uid)).all() == [
                "sent"
            ]
    finally:
        with Session(engine) as s:
            s.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
            s.commit()
        engine.dispose()


# ---------- robustness (QA) ----------


def test_us71_user_deleted_mid_run_does_not_abort_the_run(env: Env) -> None:  # noqa: F811
    gone = new_user(env.db, "America/Toronto")
    kept = new_user(env.db, "America/Toronto")
    seed(env, kept)
    stale = [gone, kept]
    env.monkeypatch.setattr(repo, "enabled_users", lambda s: stale)
    env.db.delete(gone)
    env.db.flush()
    sender = FakeEmailSender()
    run_digest(env.db, sender, NOW)
    assert len(sender.sent) == 1 and len(mine(sender, kept)) == 1


def test_us71_one_users_unexpected_error_does_not_stop_the_others(env: Env) -> None:  # noqa: F811
    bad = new_user(env.db, "America/Toronto", "bad@example.test")
    good = new_user(env.db, "America/Toronto")
    seed(env, bad)
    seed(env, good)

    class Picky(FakeEmailSender):
        def send(self, message: OutgoingEmail) -> None:
            if message.to_address == "bad@example.test":
                raise RuntimeError("boom")
            super().send(message)

    sender = Picky()
    counts = run_digest(env.db, sender, NOW)
    assert len(mine(sender, good)) == 1 and counts["failed"] >= 1


def test_us71_user_who_unsubscribed_before_the_send_is_not_emailed(env: Env) -> None:  # noqa: F811
    user = new_user(env.db, "America/Toronto")
    seed(env, user)
    env.monkeypatch.setattr(repo, "enabled_users", lambda s: [user])
    user.digest_enabled = False
    env.db.flush()
    sender = FakeEmailSender()
    run_digest(env.db, sender, NOW)
    assert sender.sent == []


def test_us71_unconfigured_provider_fails_closed_and_is_never_recorded_as_sent(
    env: Env,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.providers.email import UnconfiguredEmailSender, sender_for

    assert isinstance(sender_for("prod"), UnconfiguredEmailSender)
    assert not isinstance(sender_for("local"), UnconfiguredEmailSender)
    user = new_user(env.db, "America/Toronto")
    seed(env, user)
    with caplog.at_level("INFO"):
        run_digest(env.db, sender_for("staging"), NOW)
    assert rows(env, user)[0].status == "failed"
    assert "not_configured" in " ".join(str(r.__dict__) for r in caplog.records)


def test_us70_email_and_phone_like_company_names_are_masked(env: Env) -> None:  # noqa: F811
    assert clean_company("jane@acme.com") == "Unknown company"
    assert clean_company("Acme jane.doe@acme.com Corp") == "Acme Corp"
    assert clean_company("Acme +1 (416) 555-0123") == "Acme"
    assert clean_company("5551234567") == "Unknown company"
    assert clean_company("Studio 54") == "Studio 54"
    digest = Digest((), (Entry(clean_company("jane@acme.com"), "Applied"),), (), (), ())
    url = "https://api.example.test/u"
    assert "jane@acme.com" not in render_text(digest, url) + render_html(digest, url)
