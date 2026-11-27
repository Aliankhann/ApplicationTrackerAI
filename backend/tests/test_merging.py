"""Phase 5: one card per real application, however many threads it spans."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Application, ApplicationThread, EmailThread, StatusEvent, User
from app.providers.classifier.types import ClassificationResult, Label
from app.providers.gmail.types import MessageMeta, ThreadMeta
from app.repositories import applications as apps_repo
from app.repositories import threads as threads_repo
from app.services import applications as svc
from app.services.classification import ApplicationStatus
from app.services.extraction import Extracted
from app.services.merging import normalize_company, normalize_role

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def user_of(session: Session) -> User:
    user = User(google_sub=uuid.uuid4().hex, email="u@example.test")
    session.add(user)
    session.flush()
    return user


def thread_of(
    session: Session, user: User, key: str, *, day: int = 0, domain: str = "ats.example"
) -> EmailThread:
    sent = T0 + timedelta(days=day)
    message = MessageMeta(key, key, f"x@{domain}", "X", "s", "snip", sent, False, None, frozenset())
    return threads_repo.upsert_thread(
        session, user.id, ThreadMeta(key, "h", (message,)), "s", domain, "snip"
    )


def record(
    session: Session,
    user: User,
    thread: EmailThread,
    label: Label,
    company: str | None,
    role: str | None,
) -> Application:
    result = ClassificationResult(label, 0.9, "rules", "r", False)
    extracted = Extracted(company, role, "s" if company else None, "s" if role else None)
    application = svc.record_classification(session, user.id, thread, result, extracted, T0)
    assert application is not None
    return application


def cards(session: Session, user: User) -> int:
    return (
        session.scalar(
            select(func.count()).select_from(Application).where(Application.user_id == user.id)
        )
        or 0
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Acme Corp", "acme"),
        ("ACME, Inc.", "acme"),
        ("Acme", "acme"),
        ("Umbrella Labs", "umbrella"),
        ("Wayne Technologies LLC", "wayne"),
        ("Marlow & Finch", "marlow and finch"),
        ("Labs", "labs"),
        (None, ""),
    ],
)
def test_ac_company_normalisation_strips_case_punctuation_and_suffixes(
    raw: str | None, expected: str
) -> None:
    assert normalize_company(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Software Engineer Intern", "software engineer"),
        ("Software Engineering Internship - Summer 2027", "software engineer"),
        ("Summer 2027 Data Science Intern", "data science"),
        ("Co-op Analyst", "co op analyst"),
        ("Data Analyst Intern", "data analyst"),
        (None, ""),
    ],
)
def test_ac_role_normalisation_strips_season_year_and_intern_wording(
    raw: str | None, expected: str
) -> None:
    assert normalize_role(raw) == expected


def test_ac_two_threads_of_one_application_become_one_card(db_session: Session) -> None:
    user = user_of(db_session)
    confirmation = thread_of(db_session, user, "t1", day=0)
    interview = thread_of(db_session, user, "t2", day=10, domain="acme.example")
    first = record(
        db_session, user, confirmation, Label.CONFIRMATION, "Acme", "Software Engineer Intern"
    )
    second = record(
        db_session, user, interview, Label.INTERVIEW, "Acme Corp", "Software Engineering Internship"
    )
    assert first.id == second.id and cards(db_session, user) == 1
    assert second.status == ApplicationStatus.INTERVIEW
    linked = db_session.scalars(
        select(ApplicationThread.thread_id).where(ApplicationThread.application_id == first.id)
    ).all()
    assert set(linked) == {confirmation.id, interview.id}
    assert apps_repo.get_for_thread(db_session, user.id, interview.id) == first


def test_ac_status_stays_forward_only_across_threads_in_any_order(db_session: Session) -> None:
    user = user_of(db_session)
    late = thread_of(db_session, user, "t1", day=20)
    early = thread_of(db_session, user, "t2", day=0)
    card = record(db_session, user, late, Label.REJECTION, "Acme", "Analyst")
    again = record(db_session, user, early, Label.CONFIRMATION, "Acme", "Analyst")
    assert again.id == card.id and again.status == ApplicationStatus.REJECTED
    events = apps_repo.list_events(db_session, user.id, card.id)
    assert [e.to_status for e in events] == [ApplicationStatus.REJECTED]


def test_ac_status_events_come_from_any_thread(db_session: Session) -> None:
    user = user_of(db_session)
    card = record(
        db_session, user, thread_of(db_session, user, "t1"), Label.CONFIRMATION, "Acme", "Analyst"
    )
    record(
        db_session,
        user,
        thread_of(db_session, user, "t2", day=3),
        Label.ONLINE_ASSESSMENT,
        "Acme",
        "Analyst",
    )
    record(
        db_session,
        user,
        thread_of(db_session, user, "t3", day=6),
        Label.INTERVIEW,
        "Acme",
        "Analyst",
    )
    reasons = [e.to_status for e in apps_repo.list_events(db_session, user.id, card.id)]
    assert reasons == [
        ApplicationStatus.APPLIED,
        ApplicationStatus.ONLINE_ASSESSMENT,
        ApplicationStatus.INTERVIEW,
    ]


def test_ac_different_roles_at_one_company_never_merge(db_session: Session) -> None:
    user = user_of(db_session)
    a = record(
        db_session,
        user,
        thread_of(db_session, user, "t1"),
        Label.CONFIRMATION,
        "Acme",
        "Backend Intern",
    )
    b = record(
        db_session,
        user,
        thread_of(db_session, user, "t2", day=1),
        Label.CONFIRMATION,
        "Acme",
        "Design Intern",
    )
    assert a.id != b.id and cards(db_session, user) == 2


def test_ac_a_missing_role_on_one_side_still_merges_when_one_card_matches(
    db_session: Session,
) -> None:
    user = user_of(db_session)
    a = record(
        db_session,
        user,
        thread_of(db_session, user, "t1"),
        Label.CONFIRMATION,
        "Acme",
        "Backend Intern",
    )
    b = record(
        db_session, user, thread_of(db_session, user, "t2", day=2), Label.INTERVIEW, "Acme", None
    )
    assert a.id == b.id and b.role == "Backend Intern"


def test_ac_a_missing_role_is_ambiguous_with_two_candidate_cards(db_session: Session) -> None:
    user = user_of(db_session)
    record(
        db_session,
        user,
        thread_of(db_session, user, "t1"),
        Label.CONFIRMATION,
        "Acme",
        "Backend Intern",
    )
    record(
        db_session,
        user,
        thread_of(db_session, user, "t2", day=1),
        Label.CONFIRMATION,
        "Acme",
        "Design Intern",
    )
    third = record(
        db_session, user, thread_of(db_session, user, "t3", day=2), Label.INTERVIEW, "Acme", None
    )
    assert cards(db_session, user) == 3 and third.role is None


def test_ac_threads_more_than_45_days_apart_do_not_merge(db_session: Session) -> None:
    user = user_of(db_session)
    a = record(
        db_session,
        user,
        thread_of(db_session, user, "t1", day=0),
        Label.CONFIRMATION,
        "Acme",
        "Analyst",
    )
    near = record(
        db_session,
        user,
        thread_of(db_session, user, "t2", day=44),
        Label.INTERVIEW,
        "Acme",
        "Analyst",
    )
    far = record(
        db_session,
        user,
        thread_of(db_session, user, "t3", day=44 + 46),
        Label.CONFIRMATION,
        "Acme",
        "Analyst",
    )
    assert near.id == a.id and far.id != a.id


def test_ac_without_a_company_one_role_and_domain_match_merges(db_session: Session) -> None:
    user = user_of(db_session)
    a = record(
        db_session,
        user,
        thread_of(db_session, user, "t1", domain="hire.example"),
        Label.CONFIRMATION,
        None,
        "Data Analyst Intern",
    )
    b = record(
        db_session,
        user,
        thread_of(db_session, user, "t2", day=3, domain="hire.example"),
        Label.INTERVIEW,
        None,
        "Data Analyst",
    )
    other = record(
        db_session,
        user,
        thread_of(db_session, user, "t3", day=4, domain="else.example"),
        Label.INTERVIEW,
        None,
        "Data Analyst",
    )
    assert a.id == b.id and other.id != a.id


def test_ac_without_a_company_two_candidates_are_ambiguous(db_session: Session) -> None:
    user = user_of(db_session)
    domain = "hire.example"
    for i, company in enumerate(("Alpha", "Beta")):
        record(
            db_session,
            user,
            thread_of(db_session, user, f"t{i}", day=i, domain=domain),
            Label.CONFIRMATION,
            company,
            "Data Analyst",
        )
    third = thread_of(db_session, user, "t3", day=3, domain=domain)
    lone = record(db_session, user, third, Label.INTERVIEW, None, "Data Analyst")
    assert cards(db_session, user) == 3 and lone.company is None


def test_ac_without_company_or_role_a_thread_stays_alone(db_session: Session) -> None:
    user = user_of(db_session)
    record(
        db_session, user, thread_of(db_session, user, "t1"), Label.CONFIRMATION, "Acme", "Analyst"
    )
    lone = record(
        db_session, user, thread_of(db_session, user, "t2", day=1), Label.INTERVIEW, None, None
    )
    assert cards(db_session, user) == 2 and lone.company is None


def test_ac_manual_edits_win_and_a_locked_card_keeps_its_status(db_session: Session) -> None:
    user = user_of(db_session)
    card = record(
        db_session, user, thread_of(db_session, user, "t1"), Label.CONFIRMATION, "Acme", "Analyst"
    )
    svc.edit_details(db_session, user.id, card.id, company="Acme Robotics", role="Robotics Analyst")
    svc.set_status_manually(db_session, user.id, card.id, ApplicationStatus.OFFER, T0)
    same = record(
        db_session,
        user,
        thread_of(db_session, user, "t2", day=2),
        Label.REJECTION,
        "Acme Robotics Inc",
        "Robotics Analyst Intern",
    )
    assert same.id == card.id and cards(db_session, user) == 1
    assert (same.company, same.role, same.status) == (
        "Acme Robotics",
        "Robotics Analyst",
        ApplicationStatus.OFFER,
    )
    stranger = record(
        db_session,
        user,
        thread_of(db_session, user, "t3", day=3),
        Label.CONFIRMATION,
        "Acme",
        "Analyst",
    )
    assert stranger.id != card.id  # the user's rename took the card out of the old key


def test_ac_other_users_cards_are_never_merge_targets(db_session: Session) -> None:
    mine, theirs = user_of(db_session), user_of(db_session)
    a = record(
        db_session, mine, thread_of(db_session, mine, "t1"), Label.CONFIRMATION, "Acme", "Analyst"
    )
    b = record(
        db_session, theirs, thread_of(db_session, theirs, "t1"), Label.INTERVIEW, "Acme", "Analyst"
    )
    assert a.id != b.id and a.status == ApplicationStatus.APPLIED


def test_ac_reprocessing_a_merged_thread_creates_nothing_new(db_session: Session) -> None:
    user = user_of(db_session)
    first = thread_of(db_session, user, "t1")
    second = thread_of(db_session, user, "t2", day=3)
    card = record(db_session, user, first, Label.CONFIRMATION, "Acme", "Analyst")
    record(db_session, user, second, Label.INTERVIEW, "Acme", "Analyst")
    record(db_session, user, second, Label.INTERVIEW, "Acme", "Analyst")
    assert cards(db_session, user) == 1
    events = db_session.scalar(select(func.count()).select_from(StatusEvent))
    assert events == 2 and card.status == ApplicationStatus.INTERVIEW


def test_ac_a_card_with_no_threads_left_is_found_again_after_a_reconnect(
    db_session: Session,
) -> None:
    user = user_of(db_session)
    first = thread_of(db_session, user, "t1")
    card = record(db_session, user, first, Label.INTERVIEW, "Acme", "Analyst")
    threads_repo.delete_all(db_session, user.id)  # disconnect: threads go, cards stay
    db_session.expire_all()
    again = thread_of(db_session, user, "t1-new", day=200)
    merged = record(db_session, user, again, Label.CONFIRMATION, "Acme", "Analyst")
    assert merged.id == card.id and cards(db_session, user) == 1
