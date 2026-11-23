"""US-64/US-65: plan_followups and run_due against the fake Gmail client."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import Base
from app.models import Application, EmailThread, FollowUpTask, Sequence, SyncState, User
from app.providers.gmail.errors import GmailError, GmailRateLimited
from app.providers.gmail.fake import FakeGmailClient
from app.repositories import followups as repo
from app.services.classification import ApplicationStatus
from app.services.scheduler import RunResult, plan_followups, run_due

APPLIED = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)  # Mon 10:00 Toronto (EST)
PLANNED = APPLIED + timedelta(hours=1)
DAY7 = datetime(2026, 3, 9, 14, 0, tzinfo=UTC)  # Mon 10:00 Toronto (EDT), step 1 due 09:00
DAY14 = datetime(2026, 3, 16, 14, 0, tzinfo=UTC)
RECIPIENT = "dana.smith@acme-recruiting.example"


def make_user(session: Session, tz: str | None = None) -> User:
    user = User(google_sub=uuid.uuid4().hex, email="u@example.test", timezone=tz)
    session.add(user)
    session.flush()
    return user


def make_app(
    session: Session, user: User, client: FakeGmailClient, *, role: str = "SWE Intern"
) -> tuple[Application, str]:
    thread_id = f"t-{uuid.uuid4().hex[:8]}"
    client.add_message(
        thread_id,
        from_address=RECIPIENT,
        from_name="Dana Smith",
        subject="Your application",
        sent_at=APPLIED - timedelta(hours=1),
        rfc822_message_id="<in@acme.example>",
    )
    client.add_message(
        thread_id,
        from_address="u@example.test",
        from_user=True,
        subject="Your application",
        sent_at=APPLIED,
        rfc822_message_id="<out@me.example>",
    )
    row = EmailThread(
        user_id=user.id,
        gmail_thread_id=thread_id,
        subject="Your application",
        from_domain="acme-recruiting.example",
        snippet="",
        first_message_at=APPLIED - timedelta(hours=1),
        last_message_at=APPLIED,
        last_sender_is_user=True,
        message_count=2,
    )
    session.add(row)
    session.flush()
    app = Application(
        user_id=user.id,
        company="Acme",
        role=role,
        status=ApplicationStatus.APPLIED,
        source_thread_id=row.id,
        applied_at=APPLIED,
        last_activity_at=APPLIED,
    )
    session.add(app)
    session.flush()
    return app, thread_id


def setup(
    session: Session, tz: str | None = "America/Toronto"
) -> tuple[User, FakeGmailClient, Application, str]:
    user = make_user(session, tz)
    client = FakeGmailClient("u@example.test", now=APPLIED)
    app, thread_id = make_app(session, user, client)
    plan_followups(session, user.id, PLANNED)
    return user, client, app, thread_id


def run(session: Session, user: User, client: FakeGmailClient, now: datetime) -> RunResult:
    client.now = now
    return run_due(session, user.id, client, now, commit=session.flush)


def tasks(session: Session, user: User, app: Application) -> list[FollowUpTask]:
    return repo.for_application(session, user.id, app.id)


def test_ac7_plan_is_idempotent_with_due_dates_in_user_timezone(db_session: Session) -> None:
    user, _, app, _ = setup(db_session)
    assert plan_followups(db_session, user.id, PLANNED) == 0
    found = tasks(db_session, user, app)
    assert [t.step_index for t in found] == [0, 1]
    assert [t.due_at for t in found] == [
        datetime(2026, 3, 9, 13, 0, tzinfo=UTC),  # 09:00 EDT
        datetime(2026, 3, 16, 13, 0, tzinfo=UTC),
    ]


def test_ac7_plan_uses_default_timezone_when_user_has_none(db_session: Session) -> None:
    user, _, app, _ = setup(db_session, tz=None)
    assert tasks(db_session, user, app)[0].due_at == datetime(2026, 3, 9, 13, 0, tzinfo=UTC)
    kolkata, _, kapp, _ = setup(db_session, tz="Asia/Kolkata")
    assert tasks(db_session, kolkata, kapp)[0].due_at == datetime(2026, 3, 9, 3, 30, tzinfo=UTC)


def test_ac7_plan_skips_replied_and_closed_applications(db_session: Session) -> None:
    user = make_user(db_session)
    client = FakeGmailClient("u@example.test", now=APPLIED)
    replied, _ = make_app(db_session, user, client)
    closed, _ = make_app(db_session, user, client)
    thread = db_session.get(EmailThread, replied.source_thread_id)
    assert thread is not None
    thread.last_sender_is_user = False
    closed.status = ApplicationStatus.REJECTED
    assert plan_followups(db_session, user.id, PLANNED) == 0


def test_ac8_draft_is_a_reply_in_the_thread_and_recipient_is_never_stored(
    db_session: Session,
) -> None:
    user, client, app, thread_id = setup(db_session)
    result = run(db_session, user, client, DAY7)
    assert result == RunResult(drafted=1)
    (draft,) = client.drafts
    assert draft.thread_id == thread_id
    assert draft.in_reply_to == "<out@me.example>"
    assert draft.references == "<in@acme.example> <out@me.example>"
    assert draft.subject == "Re: Your application"
    assert draft.to == RECIPIENT
    assert draft.body_text.startswith("Hi Dana,")
    assert "SWE Intern" in draft.body_text and "March 2" in draft.body_text
    first = tasks(db_session, user, app)[0]
    assert first.state == "drafted" and first.gmail_draft_id == "fake-d1"
    for table in Base.metadata.sorted_tables:
        for row in db_session.execute(select(table)).all():
            assert RECIPIENT not in " ".join(str(v) for v in row)


@pytest.mark.parametrize(
    "reason",
    [
        "reply_received",
        "status_advanced",
        "paused",
        "user_already_sent",
        "gmail_disconnected_sync_state",
        "gmail_disconnected_exception",
    ],
)
def test_ac9_each_stop_condition_cancels_task_and_later_steps(
    db_session: Session, reason: str
) -> None:
    user, client, app, thread_id = setup(db_session)
    expected = reason.removesuffix("_sync_state").removesuffix("_exception")
    if reason == "reply_received":
        client.add_message(thread_id, from_address=RECIPIENT, sent_at=DAY7 - timedelta(hours=2))
    elif reason == "status_advanced":
        app.status = ApplicationStatus.INTERVIEW
    elif reason == "paused":
        app.followups_paused = True
    elif reason == "user_already_sent":
        client.add_message(
            thread_id,
            from_address="u@example.test",
            from_user=True,
            sent_at=PLANNED + timedelta(days=2),
        )
    elif reason == "gmail_disconnected_sync_state":
        db_session.add(SyncState(user_id=user.id, status="revoked"))
        db_session.flush()
    else:
        client.revoke()
    result = run(db_session, user, client, DAY14)
    assert client.drafts == ()
    assert result.drafted == 0 and result.cancelled == 2
    assert [(t.state, t.cancel_reason) for t in tasks(db_session, user, app)] == [
        ("cancelled", expected)
    ] * 2


def test_ac9_max_attempts_cancels_steps_missing_from_an_edited_sequence(
    db_session: Session,
) -> None:
    user, client, app, _ = setup(db_session)
    sequence = db_session.scalars(select(Sequence).where(Sequence.user_id == user.id)).one()
    sequence.steps = [sequence.steps[0]]
    db_session.flush()
    assert run(db_session, user, client, DAY14).drafted == 1
    states = [(t.state, t.cancel_reason) for t in tasks(db_session, user, app)]
    assert states == [("drafted", None), ("pending", None)]
    client.send_draft(tasks(db_session, user, app)[0].gmail_draft_id or "")
    result = run(db_session, user, client, DAY14 + timedelta(minutes=15))
    assert result.drafted == 0 and result.cancelled == 1
    assert [(t.state, t.cancel_reason) for t in tasks(db_session, user, app)] == [
        ("sent", None),
        ("cancelled", "max_attempts"),
    ]


def test_ac9_later_step_waits_while_an_earlier_draft_is_unreviewed(db_session: Session) -> None:
    user, client, app, _ = setup(db_session)
    assert run(db_session, user, client, DAY14).drafted == 1
    assert run(db_session, user, client, DAY14 + timedelta(minutes=15)).drafted == 0
    assert [t.state for t in tasks(db_session, user, app)] == ["drafted", "pending"]


def test_ac10_nothing_drafts_outside_the_window_and_weekend_waits_for_monday(
    db_session: Session,
) -> None:
    user, client, app, _ = setup(db_session)
    assert run(db_session, user, client, DAY7 + timedelta(hours=2)) == RunResult(skipped_window=1)
    first = tasks(db_session, user, app)[0]
    first.due_at = datetime(2026, 3, 14, 13, 0, tzinfo=UTC)  # Saturday
    saturday = datetime(2026, 3, 14, 14, 0, tzinfo=UTC)
    assert run(db_session, user, client, saturday).skipped_window == 1
    assert client.drafts == ()
    monday = datetime(2026, 3, 16, 13, 0, tzinfo=UTC)  # 09:00 EDT
    assert run(db_session, user, client, monday - timedelta(minutes=1)).drafted == 0
    assert run(db_session, user, client, monday).drafted == 1
    assert first.state == "drafted"


def test_daily_mode_drafts_at_run_time_on_any_weekday_but_never_on_weekends(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FOLLOWUP_WINDOW_MODE", "daily")
    get_settings.cache_clear()
    user, client, app, _ = setup(db_session)
    first, second = tasks(db_session, user, app)
    assert first.due_at == datetime(2026, 3, 9, 4, 0, tzinfo=UTC)  # local midnight (EDT)
    saturday = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)
    first.due_at = datetime(2026, 3, 13, 4, 0, tzinfo=UTC)
    assert run(db_session, user, client, saturday).skipped_window == 1 and client.drafts == ()
    monday_early = datetime(2026, 3, 16, 12, 0, tzinfo=UTC)  # 08:00 local: before any 9-11 window
    assert run(db_session, user, client, monday_early).drafted == 1
    assert (first.state, second.state) == ("drafted", "pending")  # the later step is not due yet


def test_ac11_daily_cap_holds_across_runs_and_resets_next_local_day(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FOLLOWUP_DAILY_DRAFT_CAP", "2")
    get_settings.cache_clear()
    user = make_user(db_session, "America/Toronto")
    client = FakeGmailClient("u@example.test", now=APPLIED)
    for _ in range(3):
        make_app(db_session, user, client)
    plan_followups(db_session, user.id, PLANNED)
    assert run(db_session, user, client, DAY7) == RunResult(drafted=2, skipped_cap=1)
    assert run(db_session, user, client, DAY7 + timedelta(minutes=30)) == RunResult(skipped_cap=1)
    tuesday = DAY7 + timedelta(days=1)
    assert run(db_session, user, client, tuesday) == RunResult(drafted=1)


def test_ac12_reconciliation_marks_sent_or_cancelled(db_session: Session) -> None:
    user = make_user(db_session, "America/Toronto")
    client = FakeGmailClient("u@example.test", now=APPLIED)
    sent_app, _ = make_app(db_session, user, client)
    gone_app, _ = make_app(db_session, user, client)
    plan_followups(db_session, user.id, PLANNED)
    assert run(db_session, user, client, DAY7).drafted == 2
    client.send_draft(tasks(db_session, user, sent_app)[0].gmail_draft_id or "")
    client.delete_draft(tasks(db_session, user, gone_app)[0].gmail_draft_id or "")
    result = run(db_session, user, client, DAY7 + timedelta(minutes=15))
    assert result.cancelled == 2 and result.drafted == 0
    sent = tasks(db_session, user, sent_app)
    assert (sent[0].state, sent[0].sent_at, sent[1].state) == ("sent", DAY7, "pending")
    gone = tasks(db_session, user, gone_app)
    assert [(t.state, t.cancel_reason) for t in gone] == [("cancelled", "draft_edited_or_sent")] * 2


def test_ac13_run_for_one_user_never_touches_another_users_tasks(db_session: Session) -> None:
    user_a, client_a, app_a, _ = setup(db_session)
    user_b, client_b, app_b, _ = setup(db_session)
    assert run(db_session, user_b, client_b, DAY7).drafted == 1
    assert client_a.drafts == ()
    assert [t.state for t in tasks(db_session, user_a, app_a)] == ["pending", "pending"]
    assert tasks(db_session, user_a, app_b) == []  # repository scoping
    client_b.revoke()
    run(db_session, user_b, client_b, DAY14)
    assert [t.state for t in tasks(db_session, user_a, app_a)] == ["pending", "pending"]


def test_rate_limit_stops_the_run_and_leaves_tasks_pending(db_session: Session) -> None:
    user, client, app, _ = setup(db_session)
    client.fail_next(GmailRateLimited())
    assert run(db_session, user, client, DAY7) == RunResult()
    assert [t.state for t in tasks(db_session, user, app)] == ["pending", "pending"]


def test_stale_steps_are_skipped_on_plan(db_session: Session) -> None:
    user = make_user(db_session, "America/Toronto")
    client = FakeGmailClient("u@example.test", now=APPLIED)
    app, _ = make_app(db_session, user, client)
    plan_followups(db_session, user.id, APPLIED + timedelta(days=60))
    assert [(t.state, t.cancel_reason) for t in tasks(db_session, user, app)] == [
        ("skipped", "stale_on_plan")
    ] * 2
    fresh = make_user(db_session, "America/Toronto")
    fresh_app, _ = make_app(db_session, fresh, client)
    plan_followups(db_session, fresh.id, APPLIED + timedelta(days=5))
    assert [t.state for t in tasks(db_session, fresh, fresh_app)] == ["pending", "pending"]


def test_second_concurrent_run_does_nothing_while_lease_is_held(db_session: Session) -> None:
    user, client, _, _ = setup(db_session)
    assert repo.claim_lease(db_session, user.id, DAY7, timedelta(minutes=15))
    assert run(db_session, user, client, DAY7).already_running
    assert client.drafts == ()
    assert run(db_session, user, client, DAY7 + timedelta(minutes=20)).drafted == 1


def test_stale_claim_with_a_draft_is_cancelled_never_redrafted(db_session: Session) -> None:
    user, client, app, thread_id = setup(db_session)
    first = tasks(db_session, user, app)[0]
    first.state, first.claimed_at = "drafting", DAY7 - timedelta(minutes=30)
    client.add_message(
        thread_id,
        from_address="u@example.test",
        from_user=True,
        sent_at=DAY7 - timedelta(minutes=29),
        label_ids=frozenset({"DRAFT"}),
    )
    run(db_session, user, client, DAY7)
    assert [(t.state, t.cancel_reason) for t in tasks(db_session, user, app)] == [
        ("cancelled", "uncertain_draft")
    ] * 2
    assert client.drafts == ()


def test_stale_claim_without_a_draft_goes_back_to_pending_and_drafts(db_session: Session) -> None:
    user, client, app, _ = setup(db_session)
    first = tasks(db_session, user, app)[0]
    first.state, first.claimed_at = "drafting", DAY7 - timedelta(minutes=30)
    assert run(db_session, user, client, DAY7).drafted == 1


def test_poison_task_is_released_then_cancelled_after_three_failures(db_session: Session) -> None:
    user, client, app, _ = setup(db_session)
    for expected in (1, 2):
        client.fail_next(GmailError("boom"))
        run(db_session, user, client, DAY7 + timedelta(minutes=expected))
        first = tasks(db_session, user, app)[0]
        assert (first.state, first.attempt_failures) == ("pending", expected)
    client.fail_next(GmailError("boom"))
    result = run(db_session, user, client, DAY7 + timedelta(minutes=5))
    assert result.cancelled == 2
    assert [(t.state, t.cancel_reason) for t in tasks(db_session, user, app)] == [
        ("cancelled", "gmail_error")
    ] * 2


def test_one_failing_task_does_not_block_the_next(db_session: Session) -> None:
    user = make_user(db_session, "America/Toronto")
    client = FakeGmailClient("u@example.test", now=APPLIED)
    make_app(db_session, user, client)
    make_app(db_session, user, client)
    plan_followups(db_session, user.id, PLANNED)
    client.fail_next(GmailError("boom"))
    assert run(db_session, user, client, DAY7).drafted == 1


@pytest.mark.parametrize(
    ("address", "reason"),
    [
        ("no-reply@acme.example", "no_reply_recipient"),
        ("Do.Not.Reply@acme.example", "no_reply_recipient"),
        ("notifications@acme.example", "no_reply_recipient"),
        ("mailer-daemon@acme.example", "no_reply_recipient"),
        ("U@Example.test", "self_recipient"),
    ],
)
def test_unusable_recipients_cancel_without_storing_the_address(
    db_session: Session, address: str, reason: str
) -> None:
    user, client, app, thread_id = setup(db_session)
    client.add_message(thread_id, from_address=address, sent_at=APPLIED - timedelta(minutes=5))
    client.add_message(
        thread_id,
        from_address="u@example.test",
        from_user=True,
        sent_at=APPLIED + timedelta(minutes=1),
    )
    run(db_session, user, client, DAY7)
    assert [(t.state, t.cancel_reason) for t in tasks(db_session, user, app)] == [
        ("cancelled", reason)
    ] * 2
    assert client.drafts == ()


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Dana Smith", "Hi Dana,"),
        ("Dana", "Hi there,"),
        ("Acme Recruiting", "Hi there,"),
        ("Greenhouse Notifications", "Hi there,"),
        ("dana smith", "Hi there,"),
        ("Acme Careers", "Hi there,"),
    ],
)
def test_first_name_only_for_clearly_personal_sender_names(
    db_session: Session, name: str, expected: str
) -> None:
    user, client, _, thread_id = setup(db_session)
    client.add_message(
        thread_id,
        from_address="x@acme.example",
        from_name=name,
        sent_at=APPLIED - timedelta(minutes=5),
    )
    client.add_message(
        thread_id,
        from_address="u@example.test",
        from_user=True,
        sent_at=APPLIED + timedelta(minutes=1),
    )
    run(db_session, user, client, DAY7)
    assert client.drafts[0].body_text.startswith(expected)


def test_delayed_step_zero_keeps_step_one_from_drafting_first(db_session: Session) -> None:
    user, client, app, _ = setup(db_session)
    first, second = tasks(db_session, user, app)
    first.due_at = DAY14 + timedelta(days=30)  # delayed past step 1's due date
    db_session.flush()
    result = run(db_session, user, client, DAY14)
    assert (result.drafted, result.waiting_earlier_step) == (0, 1)
    assert [t.state for t in tasks(db_session, user, app)] == ["pending", "pending"]
    assert second.state == "pending"
