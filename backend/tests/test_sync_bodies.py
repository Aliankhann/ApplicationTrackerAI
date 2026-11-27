# ruff: noqa: E501
"""Phases 1 and 3: message text is read in memory only; every new message is classified once."""

import logging
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Application, Classification, EmailThread
from app.providers.classifier.base import ClassifierProvider
from app.providers.classifier.router import RoutedClassifier
from app.providers.classifier.rules import RulesProvider
from app.providers.classifier.types import ClassificationInput, ClassificationResult
from app.providers.gmail import (
    FakeGmailClient,
    GmailAuthRevoked,
    GmailError,
    GmailNotFound,
    GmailRateLimited,
    MessageMeta,
)
from app.services import sync
from app.services.classification import ApplicationStatus
from app.services.llm_controls import LlmControls
from app.services.sync import SyncPaused, SyncResult, SyncRevoked, run_sync
from tests.fixtures.gmail_threads import OWNER
from tests.test_llm_classifier import MODEL, FakeClient, provider, response
from tests.test_sync import NOW, force_full_pass, make_user

DAY = timedelta(days=1)
MARKER = "ZEBRA-QUOKKA-PRIVATE-BODY-TEXT"
REJECTION = "Unfortunately we will not be moving forward with your application."


def message(
    thread: str,
    n: int,
    *,
    days: int = 2,
    sender: str = "jobs@acme-robotics.example",
    name: str = "Acme Robotics Careers",
    subject: str = "Acme Robotics update",
    snippet: str = "Hi Sam, thanks for your interest in Acme Robotics.",
    from_user: bool = False,
) -> MessageMeta:
    return MessageMeta(
        message_id=f"{thread}-{n}",
        thread_id=thread,
        from_address=OWNER if from_user else sender,
        from_name=name,
        subject=subject,
        snippet=snippet,
        sent_at=NOW - days * DAY + timedelta(minutes=n),
        from_user=from_user,
        rfc822_message_id=None,
        label_ids=frozenset({"SENT" if from_user else "INBOX"}),
    )


def run(
    session: Session,
    user_id: uuid.UUID,
    client: FakeGmailClient,
    classifier: ClassifierProvider | None = None,
    **kwargs: object,
) -> SyncResult:
    result = run_sync(
        session,
        user_id,
        client,
        classifier or RulesProvider(),
        NOW,
        commit=session.flush,
        sleep=lambda _s: None,
        **kwargs,  # type: ignore[arg-type]
    )
    assert isinstance(result, SyncResult)
    return result


def one_thread(*messages: MessageMeta) -> FakeGmailClient:
    return FakeGmailClient(OWNER, {messages[0].thread_id: list(messages)}, now=NOW)


def card(session: Session, user_id: uuid.UUID) -> Application:
    return session.scalars(select(Application).where(Application.user_id == user_id)).one()


@pytest.fixture
def user_id(db_session: Session) -> uuid.UUID:
    return make_user(db_session)


def test_ac_the_body_decides_when_the_snippet_cannot(
    db_session: Session, user_id: uuid.UUID
) -> None:
    msg = message("t1", 0)
    client = one_thread(msg)
    client.set_body(
        msg.message_id, f"Hi Sam,\n\nThank you for your interest.\n\n{REJECTION}\n\nRegards"
    )
    run(db_session, user_id, client)
    assert card(db_session, user_id).status == ApplicationStatus.REJECTED
    assert client.body_fetches == [msg.message_id]


def test_ac_no_body_means_the_snippet_decides_as_before(
    db_session: Session, user_id: uuid.UUID
) -> None:
    msg = message("t1", 0, snippet=REJECTION)
    run(db_session, user_id, one_thread(msg))  # the fake serves no text: empty body
    assert card(db_session, user_id).status == ApplicationStatus.REJECTED


def test_ac_bodies_are_only_fetched_for_threads_the_prefilter_keeps(
    db_session: Session, user_id: uuid.UUID
) -> None:
    junk = message(
        "t-junk",
        0,
        sender="deals@shop.example",
        name="Shop",
        subject="Weekend sale",
        snippet="Everything must go",
    )
    kept = message("t-kept", 0, snippet=REJECTION)
    client = FakeGmailClient(OWNER, {"t-junk": [junk], "t-kept": [kept]}, now=NOW)
    run(db_session, user_id, client)
    assert client.body_fetches == [kept.message_id]


@pytest.mark.parametrize("error", [GmailNotFound("gone"), GmailError("boom")])
def test_ac_a_failed_body_fetch_falls_back_to_the_snippet(
    db_session: Session, user_id: uuid.UUID, error: GmailError
) -> None:
    msg = message("t1", 0, snippet=REJECTION)
    client = one_thread(msg)
    client.body_error = error
    result = run(db_session, user_id, client)
    assert result.threads_kept == 1
    assert card(db_session, user_id).status == ApplicationStatus.REJECTED


def test_ac_a_revoked_grant_while_fetching_a_body_is_still_a_revoked_sync(
    db_session: Session, user_id: uuid.UUID
) -> None:
    client = one_thread(message("t1", 0))
    client.body_error = GmailAuthRevoked()
    with pytest.raises(SyncRevoked):
        run_sync(db_session, user_id, client, RulesProvider(), NOW, commit=db_session.flush)


def test_ac_rate_limited_body_fetches_pause_the_sync_like_any_gmail_call(
    db_session: Session, user_id: uuid.UUID
) -> None:
    client = one_thread(message("t1", 0))
    client.body_error = GmailRateLimited()
    outcome = run_sync(
        db_session,
        user_id,
        client,
        RulesProvider(),
        NOW,
        commit=db_session.flush,
        sleep=lambda _s: None,
    )
    assert isinstance(outcome, SyncPaused)


def test_ac_out_of_time_reads_the_snippet_alone(db_session: Session, user_id: uuid.UUID) -> None:
    client = one_thread(message("t1", 0))
    ctx = sync._Context(
        db_session,
        user_id,
        client,
        RulesProvider(),
        NOW,
        db_session.flush,
        lambda _s: None,
        lambda: NOW,
        False,
        NOW - DAY,  # the deadline has passed
        False,
    )
    assert sync._message_text(ctx, message("t1", 0)) == ""
    assert client.body_fetches == []


def test_ac_the_body_never_reaches_the_database_or_logs(
    db_session: Session, user_id: uuid.UUID, caplog: pytest.LogCaptureFixture
) -> None:
    msg = message("t1", 0)
    client = one_thread(msg)
    client.set_body(
        msg.message_id, f"{MARKER}\n{REJECTION}\nBest regards,\nThe Acme Robotics Recruiting Team"
    )
    with caplog.at_level(logging.DEBUG):
        run(db_session, user_id, client)
    assert MARKER not in caplog.text
    assert card(db_session, user_id).company == "Acme Robotics"
    tables = db_session.execute(
        text("select table_name from information_schema.tables where table_schema='public'")
    ).scalars()
    for table in tables:
        dump = db_session.execute(text(f'select t::text from "{table}" t')).scalars().all()  # noqa: S608
        assert not any(MARKER in row for row in dump), table


def test_ac_the_llm_never_receives_the_body(db_session: Session, user_id: uuid.UUID) -> None:
    llm, fake_client = provider(
        response('{"label": null, "company": null, "role": null, "confidence": 0.1}')
    )
    routed = RoutedClassifier(RulesProvider(), llm, None)
    msg = message("t1", 0, snippet="Hello there")
    client = one_thread(msg)
    client.set_body(msg.message_id, f"{MARKER} no rule matches this sentence at all")
    run(db_session, user_id, client, routed)
    assert fake_client.messages.calls, "the LLM fallback should have been asked"
    for call in fake_client.messages.calls:
        assert MARKER not in repr(call)
    assert isinstance(fake_client, FakeClient) and MODEL


def test_ac_classifier_input_carries_the_body_but_the_cache_key_and_prompt_do_not() -> None:
    from app.providers.classifier.cache import cache_key
    from app.providers.classifier.claude import build_user_message

    plain = ClassificationInput("d.example", "s", "n")
    with_body = replace(plain, body=MARKER)
    assert cache_key(plain) == cache_key(with_body)
    assert MARKER not in build_user_message(with_body)


def test_ac_every_new_message_is_classified_once_with_a_row_keyed_by_message_id(
    db_session: Session, user_id: uuid.UUID
) -> None:
    first = message("t1", 0, days=6, snippet="Thank you for applying to Acme Robotics.")
    second = message("t1", 1, days=3, snippet="Please schedule an interview with our team.")
    client = one_thread(first, second)
    run(db_session, user_id, client)
    rows = db_session.scalars(select(Classification)).all()
    assert sorted(r.gmail_message_id or "" for r in rows) == [first.message_id, second.message_id]
    classified = len(rows)
    run(db_session, user_id, client, force=False)
    assert len(db_session.scalars(select(Classification)).all()) == classified


def test_ac_a_later_message_is_classified_alone_and_applied_forward_only(
    db_session: Session, user_id: uuid.UUID
) -> None:
    first = message("t1", 0, days=6, snippet="Please schedule an interview with our team.")
    client = one_thread(first)
    run(db_session, user_id, client)
    assert card(db_session, user_id).status == ApplicationStatus.INTERVIEW
    client.add_message(
        "t1",
        from_address="jobs@acme-robotics.example",
        subject="Acme Robotics",
        snippet="Thank you for applying to Acme Robotics.",
        sent_at=NOW - DAY,
    )
    classifier = CountingRules()
    run(db_session, user_id, client, classifier)
    assert classifier.calls == 1
    assert card(db_session, user_id).status == ApplicationStatus.INTERVIEW  # never moves back


def test_ac_an_acknowledgement_after_an_invite_cannot_hide_it(
    db_session: Session, user_id: uuid.UUID
) -> None:
    invite = message("t1", 0, days=6, snippet="We would like to schedule an interview with you.")
    reply = message("t1", 1, days=5, from_user=True, snippet="Thursday works for me!")
    ack = message("t1", 2, days=4, snippet="Great, I'll send a calendar invite shortly.")
    run(db_session, user_id, one_thread(invite, reply, ack))
    assert card(db_session, user_id).status == ApplicationStatus.INTERVIEW


def test_ac_at_most_the_last_five_messages_from_others_are_classified(
    db_session: Session, user_id: uuid.UUID
) -> None:
    messages = [
        message("t1", n, days=20 - n, snippet=f"Update number {n} from Acme") for n in range(8)
    ]
    messages.append(message("t1", 9, days=1, from_user=True, snippet="my reply"))
    client = one_thread(*messages)
    classifier = CountingRules()
    run(db_session, user_id, client, classifier)
    assert classifier.calls == 5
    assert client.body_fetches == [f"t1-{n}" for n in range(3, 8)]


def test_ac_drafts_and_the_users_own_messages_are_never_classified(
    db_session: Session, user_id: uuid.UUID
) -> None:
    invite = message("t1", 0, days=6, snippet="We would like to schedule an interview with you.")
    mine = message("t1", 1, days=5, from_user=True, snippet="Thank you for applying, regards")
    draft = replace(message("t1", 2, days=4, from_user=True), label_ids=frozenset({"DRAFT"}))
    classifier = CountingRules()
    run(db_session, user_id, one_thread(invite, mine, draft), classifier)
    assert classifier.calls == 1


def test_ac_forcing_reclassifies_every_message_in_place(
    db_session: Session, user_id: uuid.UUID
) -> None:
    msg = message("t1", 0, snippet="Thank you for applying to Acme Robotics.")
    client = one_thread(msg)
    run(db_session, user_id, client)
    force_full_pass(db_session, user_id)
    classifier = CountingRules()
    run(db_session, user_id, client, classifier, force=True)
    assert classifier.calls == 1
    assert len(db_session.scalars(select(Classification)).all()) == 1


def test_ac_the_thread_row_still_holds_only_subject_domain_and_a_short_snippet(
    db_session: Session, user_id: uuid.UUID
) -> None:
    msg = message("t1", 0, snippet="y" * 400)
    client = one_thread(msg)
    client.set_body(msg.message_id, "z" * 8000 + REJECTION)
    run(db_session, user_id, client)
    row = db_session.scalars(select(EmailThread)).one()
    assert len(row.snippet) <= 200 and "z" * 50 not in row.snippet


class CountingRules:
    def __init__(self) -> None:
        self.calls = 0
        self._rules = RulesProvider()

    def classify(self, inp: ClassificationInput) -> ClassificationResult:
        self.calls += 1
        return self._rules.classify(inp)


_ = (LlmControls, UTC, datetime)  # imported for the shared fixtures' types


def test_ac_an_undecided_ats_thread_becomes_a_needs_review_card_never_vanishes(
    db_session: Session, user_id: uuid.UUID
) -> None:
    msg = message(
        "t1",
        0,
        sender="no-reply@us.greenhouse-mail.io",
        snippet="Hi Sam, a quick update on things.",
    )
    result = run(db_session, user_id, one_thread(msg))
    review = card(db_session, user_id)
    assert (review.needs_review, review.company) == (True, "Acme Robotics")
    assert result.applications_changed == 0


def test_ac_a_weak_label_becomes_the_suggestion(db_session: Session, user_id: uuid.UUID) -> None:
    msg = message("t1", 0, snippet="Hi Sam, we are hosting an on-site next week and a next round.")
    client = one_thread(msg)
    client.set_body(
        msg.message_id, "Please confirmed: 30 Minute Chat with Dana about your application."
    )
    run(db_session, user_id, client)
    review = card(db_session, user_id)
    assert review.needs_review and review.suggested_label == "interview"


def test_ac_a_dismissed_review_card_is_not_recreated_by_later_syncs(
    db_session: Session, user_id: uuid.UUID
) -> None:
    from app.services import applications as applications_service

    msg = message(
        "t1",
        0,
        sender="no-reply@us.greenhouse-mail.io",
        snippet="Hi Sam, a quick update on things.",
    )
    client = one_thread(msg)
    run(db_session, user_id, client)
    applications_service.dismiss_review(db_session, user_id, card(db_session, user_id).id, NOW)
    force_full_pass(db_session, user_id)
    run(db_session, user_id, client, force=True)
    assert len(db_session.scalars(select(Application)).all()) == 1
    assert card(db_session, user_id).dismissed_at is not None


def test_ac_job_keyword_mail_that_is_not_about_an_application_gets_no_card(
    db_session: Session, user_id: uuid.UUID
) -> None:
    msg = message(
        "t1",
        0,
        sender="news@careers-weekly.example",
        name="Careers Weekly",
        subject="Top internship tips",
        snippet="This week: how to write a resume and what recruiters look for.",
    )
    run(db_session, user_id, one_thread(msg))
    assert db_session.scalars(select(Application)).all() == []


def test_ac_threads_of_one_application_end_on_one_card_through_sync(
    db_session: Session, user_id: uuid.UUID
) -> None:
    conf = message(
        "t-a",
        0,
        days=10,
        sender="no-reply@us.greenhouse-mail.io",
        name="Acme Robotics",
        subject="Thank you for applying to Acme Robotics",
        snippet="Thank you for applying to the Backend Intern position at Acme Robotics.",
    )
    invite = message(
        "t-b",
        0,
        days=3,
        sender="rosa@acme-robotics.example",
        name="Rosa Delgado",
        subject="Interview for the Backend Intern role at Acme Robotics",
        snippet="We would like to schedule an interview for the Backend Intern role at Acme Robotics.",
    )
    client = FakeGmailClient(OWNER, {"t-a": [conf], "t-b": [invite]}, now=NOW)
    run(db_session, user_id, client)
    final = card(db_session, user_id)
    assert (final.company, final.role, final.status) == (
        "Acme Robotics",
        "Backend Intern",
        ApplicationStatus.INTERVIEW,
    )
