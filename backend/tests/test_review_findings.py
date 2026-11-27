"""Adversarial checks from the review of body reading and merging."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Application, ApplicationThread
from app.providers.classifier.rules import RulesProvider
from app.providers.classifier.types import ClassificationInput, Label
from app.services import applications as svc
from app.services.account import disconnect_gmail  # noqa: F401
from app.services.body_text import prepare_body
from app.services.classification import ApplicationStatus
from tests.test_merging import T0, cards, record, thread_of, user_of

CONFIRMATION_PREFIX = "We have received your application for the Software Engineer Intern role. "


def _label(body: str) -> Label | None:
    result = RulesProvider().classify(
        ClassificationInput(
            "greenhouse.io",
            "Thank you for applying to Acme",
            "Thank you for applying",
            prepare_body(CONFIRMATION_PREFIX + body),
        )
    )
    return None if result.needs_review else result.label


@pytest.mark.parametrize(
    "boilerplate",
    [
        "If we are unable to move forward with your application, you will receive an email.",
        "If we decide to move forward with other candidates, you will be notified.",
        "Should we decide to proceed with other candidates we will email you.",
    ],
)
def test_conditional_rejection_boilerplate_in_a_confirmation_is_not_a_rejection(
    boilerplate: str,
) -> None:
    assert _label(boilerplate) is not Label.REJECTION


@pytest.mark.parametrize(
    "boilerplate",
    [
        "We will schedule an interview if you are selected.",
        "We will contact you to schedule an interview if your background is a match.",
    ],
)
def test_trailing_conditional_interview_boilerplate_is_not_an_interview(boilerplate: str) -> None:
    assert _label(boilerplate) is not Label.INTERVIEW


def test_no_company_thread_from_a_shared_ats_domain_does_not_join_another_companys_card(
    db_session: Session,
) -> None:
    user = user_of(db_session)
    beta = record(
        db_session,
        user,
        thread_of(db_session, user, "a", domain="greenhouse.io"),
        Label.CONFIRMATION,
        "Beta Corp",
        "Software Engineer",
    )
    record(
        db_session,
        user,
        thread_of(db_session, user, "b", day=3, domain="greenhouse.io"),
        Label.INTERVIEW,
        None,
        "Software Engineer",
    )
    assert cards(db_session, user) == 2
    assert beta.status == ApplicationStatus.APPLIED


def test_two_users_with_identical_company_and_role_never_share_a_card(db_session: Session) -> None:
    one, two = user_of(db_session), user_of(db_session)
    a = record(db_session, one, thread_of(db_session, one, "a"), Label.CONFIRMATION, "Acme", "Dev")
    b = record(db_session, two, thread_of(db_session, two, "b"), Label.INTERVIEW, "Acme", "Dev")
    assert a.id != b.id and a.user_id == one.id and b.user_id == two.id
    assert a.status == ApplicationStatus.APPLIED


def test_confirm_does_not_lock_so_a_later_rejection_in_the_thread_applies(
    db_session: Session,
) -> None:
    from app.providers.classifier.types import ClassificationResult
    from app.services.extraction import Extracted

    user = user_of(db_session)
    thread = thread_of(db_session, user, "t1")
    card = svc.record_undecided(
        db_session, user.id, thread, Label.INTERVIEW, Extracted("Acme", None, "s", None), T0
    )
    assert card is not None
    svc.confirm_review(db_session, user.id, card.id, T0)
    assert not card.status_locked and card.status == ApplicationStatus.INTERVIEW
    svc.record_classification(
        db_session,
        user.id,
        thread,
        ClassificationResult(Label.REJECTION, 0.9, "rules", "r", False),
        Extracted(None, None, None, None),
        T0,
        "m2",
    )
    assert card.status is ApplicationStatus.REJECTED  # type: ignore[comparison-overlap]


def test_link_rows_are_removed_with_their_threads(db_session: Session) -> None:
    from app.repositories import threads as threads_repo

    user = user_of(db_session)
    record(db_session, user, thread_of(db_session, user, "a"), Label.CONFIRMATION, "Acme", "Dev")
    record(
        db_session, user, thread_of(db_session, user, "b", day=2), Label.INTERVIEW, "Acme", "Dev"
    )
    assert db_session.scalar(select(func.count()).select_from(ApplicationThread)) == 2
    threads_repo.delete_all(db_session, user.id)
    db_session.expire_all()
    assert db_session.scalar(select(func.count()).select_from(ApplicationThread)) == 0
    assert db_session.scalar(select(func.count()).select_from(Application)) == 1
