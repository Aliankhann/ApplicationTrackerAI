"""Phase 6: job threads nothing could decide become "Needs review" cards, never vanish."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Application, EmailThread, FollowUpTask, StatusEvent, User
from app.providers.classifier.types import ClassificationResult, Label
from app.providers.gmail.types import MessageMeta, ThreadMeta
from app.repositories import applications as apps_repo
from app.repositories import followups as followups_repo
from app.repositories import threads as threads_repo
from app.services import applications as svc
from app.services.classification import ApplicationStatus
from app.services.extraction import Extracted
from tests.test_applications_api import CSRF, login
from tests.test_sessions import Env, env  # noqa: F401

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def user_of(session: Session) -> User:
    user = User(google_sub=uuid.uuid4().hex, email="u@example.test")
    session.add(user)
    session.flush()
    return user


def thread_of(session: Session, user: User, key: str, *, from_user: bool = False) -> EmailThread:
    message = MessageMeta(
        key, key, "x@ats.example", "X", "Subj", "snip", T0, from_user, None, frozenset()
    )
    return threads_repo.upsert_thread(
        session, user.id, ThreadMeta(key, "h", (message,)), "Subj", "ats.example", "snip"
    )


def review_card(
    session: Session,
    user: User,
    key: str = "t1",
    suggested: Label | None = Label.INTERVIEW,
    company: str | None = "Acme",
) -> Application:
    extracted = Extracted(company, None, "s" if company else None, None)
    card = svc.record_undecided(
        session, user.id, thread_of(session, user, key), suggested, extracted, T0
    )
    assert card is not None
    return card


def decisive(label: Label) -> ClassificationResult:
    return ClassificationResult(label, 0.9, "rules", "r", False)


def test_ac_an_undecided_job_thread_becomes_a_needs_review_card_with_a_suggestion(
    db_session: Session,
) -> None:
    user = user_of(db_session)
    card = review_card(db_session, user)
    assert card.needs_review and card.suggested_label == "interview"
    assert card.status == ApplicationStatus.INTERVIEW  # a placeholder until the user decides
    assert apps_repo.list_events(db_session, user.id, card.id) == []  # no timeline noise


def test_ac_a_review_card_without_a_suggestion_is_still_created(db_session: Session) -> None:
    user = user_of(db_session)
    card = review_card(db_session, user, suggested=None, company=None)
    assert card.needs_review and card.suggested_label is None


def test_ac_an_undecided_thread_that_matches_a_card_joins_it_instead(db_session: Session) -> None:
    user = user_of(db_session)
    first = thread_of(db_session, user, "t1")
    extracted = Extracted("Acme", "Analyst", "s", "s")
    card = svc.record_classification(
        db_session, user.id, first, decisive(Label.CONFIRMATION), extracted, T0
    )
    joined = svc.record_undecided(
        db_session, user.id, thread_of(db_session, user, "t2"), None, extracted, T0
    )
    assert card is not None and joined is not None and joined.id == card.id
    assert not joined.needs_review and joined.status == ApplicationStatus.APPLIED


def test_ac_reprocessing_does_not_duplicate_a_review_card(db_session: Session) -> None:
    user = user_of(db_session)
    first = review_card(db_session, user, suggested=None)
    thread = thread_of(db_session, user, "t1")
    again = svc.record_undecided(
        db_session, user.id, thread, Label.OFFER, Extracted("Acme", None, "s", None), T0
    )
    assert again is not None and again.id == first.id and again.suggested_label == "offer"
    count = db_session.scalars(select(Application).where(Application.user_id == user.id)).all()
    assert len(count) == 1


def test_ac_a_decisive_message_later_turns_the_card_into_a_normal_one(db_session: Session) -> None:
    user = user_of(db_session)
    card = review_card(db_session, user)
    thread = thread_of(db_session, user, "t1")
    after = svc.record_classification(
        db_session,
        user.id,
        thread,
        decisive(Label.REJECTION),
        Extracted(None, None, None, None),
        T0,
    )
    assert after is not None and after.id == card.id
    assert (after.needs_review, after.suggested_label) == (False, None)
    assert after.status == ApplicationStatus.REJECTED


def test_ac_confirm_applies_the_suggestion_without_locking_the_status(db_session: Session) -> None:
    user = user_of(db_session)
    card = review_card(db_session, user, suggested=Label.ONLINE_ASSESSMENT)
    done = svc.confirm_review(db_session, user.id, card.id, T0)
    assert (done.needs_review, done.status, done.status_locked) == (
        False,
        ApplicationStatus.ONLINE_ASSESSMENT,
        False,
    )
    events = apps_repo.list_events(db_session, user.id, card.id)
    assert [e.reason for e in events] == ["reviewed"]


def test_ac_confirm_without_a_suggestion_or_on_a_normal_card_is_refused(
    db_session: Session,
) -> None:
    import pytest

    from app.errors import InvalidOperation

    user = user_of(db_session)
    bare = review_card(db_session, user, "t1", suggested=None)
    with pytest.raises(InvalidOperation):
        svc.confirm_review(db_session, user.id, bare.id, T0)
    normal = svc.record_classification(
        db_session,
        user.id,
        thread_of(db_session, user, "t2"),
        decisive(Label.CONFIRMATION),
        Extracted("Zed", "Dev", "s", "s"),
        T0,
    )
    assert normal is not None
    with pytest.raises(InvalidOperation):
        svc.confirm_review(db_session, user.id, normal.id, T0)


def test_ac_change_sets_the_status_by_hand_and_clears_the_review_state(
    db_session: Session,
) -> None:
    user = user_of(db_session)
    card = review_card(db_session, user)
    changed = svc.set_status_manually(db_session, user.id, card.id, ApplicationStatus.OFFER, T0)
    assert (changed.needs_review, changed.suggested_label, changed.status_locked) == (
        False,
        None,
        True,
    )
    assert [e.to_status for e in apps_repo.list_events(db_session, user.id, card.id)] == [
        ApplicationStatus.OFFER
    ]


def test_ac_change_to_the_placeholder_status_still_records_the_decision(
    db_session: Session,
) -> None:
    user = user_of(db_session)
    card = review_card(db_session, user, suggested=None)  # placeholder status is "applied"
    changed = svc.set_status_manually(db_session, user.id, card.id, ApplicationStatus.APPLIED, T0)
    assert changed.needs_review is False
    assert len(db_session.scalars(select(StatusEvent)).all()) == 1


def test_ac_dismiss_hides_the_card_and_a_later_sync_does_not_recreate_it(
    db_session: Session,
) -> None:
    user = user_of(db_session)
    card = review_card(db_session, user)
    svc.dismiss_review(db_session, user.id, card.id, T0)
    assert card.dismissed_at is not None
    thread = thread_of(db_session, user, "t1")
    again = svc.record_undecided(
        db_session, user.id, thread, Label.INTERVIEW, Extracted("Acme", None, "s", None), T0
    )
    assert again is not None and again.id == card.id
    assert len(db_session.scalars(select(Application)).all()) == 1


def test_ac_a_decisive_message_brings_a_dismissed_card_back(db_session: Session) -> None:
    user = user_of(db_session)
    card = review_card(db_session, user)
    svc.dismiss_review(db_session, user.id, card.id, T0)
    thread = thread_of(db_session, user, "t1")
    later = T0 + timedelta(hours=1)
    back = svc.record_classification(
        db_session,
        user.id,
        thread,
        decisive(Label.INTERVIEW),
        Extracted(None, None, None, None),
        later,
        "m-new",
        later,
    )
    assert back is not None and back.dismissed_at is None and not back.needs_review


def test_ac_only_a_review_card_can_be_dismissed_and_only_by_its_owner(
    db_session: Session,
) -> None:
    import pytest

    from app.errors import InvalidOperation, NotFound

    owner, other = user_of(db_session), user_of(db_session)
    normal = svc.record_classification(
        db_session,
        owner.id,
        thread_of(db_session, owner, "t1"),
        decisive(Label.CONFIRMATION),
        Extracted("Zed", "Dev", "s", "s"),
        T0,
    )
    card = review_card(db_session, owner, "t2")
    assert normal is not None
    with pytest.raises(InvalidOperation):
        svc.dismiss_review(db_session, owner.id, normal.id, T0)
    with pytest.raises(NotFound):
        svc.dismiss_review(db_session, other.id, card.id, T0)
    with pytest.raises(NotFound):
        svc.confirm_review(db_session, other.id, card.id, T0)


def test_ac_review_cards_get_no_follow_ups(db_session: Session) -> None:
    user = user_of(db_session)
    thread = thread_of(db_session, user, "t1", from_user=True)
    card = svc.record_undecided(
        db_session, user.id, thread, Label.CONFIRMATION, Extracted("Acme", None, "s", None), T0
    )
    assert card is not None
    assert followups_repo.plannable(db_session, user.id) == []
    assert db_session.scalars(select(FollowUpTask)).all() == []


# API


def test_ac_api_lists_review_cards_as_their_own_status_with_the_suggestion(env: Env) -> None:  # noqa: F811
    user = env.user()
    card = review_card(env.db, user)
    client = login(env, user)
    listed = client.get("/applications", params={"status": "needs_review"}).json()["items"]
    assert [i["id"] for i in listed] == [str(card.id)]
    assert listed[0]["display_status"] == "needs_review"
    assert (listed[0]["needs_review"], listed[0]["suggested_label"]) == (True, "interview")
    assert client.get("/applications", params={"status": "interview"}).json()["items"] == []
    assert client.get("/applications", params={"status": "applied"}).json()["items"] == []


def test_ac_api_confirm_then_card_moves_out_of_review(env: Env) -> None:  # noqa: F811
    user = env.user()
    card = review_card(env.db, user)
    client = login(env, user)
    response = client.post(f"/applications/{card.id}/confirm")
    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["display_status"], body["needs_review"]) == (
        "interview",
        "interview",
        False,
    )
    assert body["suggested_label"] is None and body["status_locked"] is False
    assert client.post(f"/applications/{card.id}/confirm").status_code == 409


def test_ac_api_change_uses_patch_status(env: Env) -> None:  # noqa: F811
    user = env.user()
    card = review_card(env.db, user)
    client = login(env, user)
    body = client.patch(f"/applications/{card.id}", json={"status": "rejected"}).json()
    assert (body["status"], body["needs_review"]) == ("rejected", False)


def test_ac_api_dismiss_hides_the_card_everywhere(env: Env) -> None:  # noqa: F811
    user = env.user()
    card = review_card(env.db, user)
    client = login(env, user)
    assert client.post(f"/applications/{card.id}/dismiss").status_code == 204
    assert client.get("/applications").json()["items"] == []
    assert client.get(f"/applications/{card.id}").status_code == 404
    assert client.post(f"/applications/{card.id}/dismiss").status_code == 404


def test_ac_api_review_actions_need_csrf_and_the_owner(env: Env) -> None:  # noqa: F811
    owner, stranger = env.user(), env.user()
    card = review_card(env.db, owner)
    assert login(env, stranger).post(f"/applications/{card.id}/confirm").status_code == 404
    assert login(env, stranger).post(f"/applications/{card.id}/dismiss").status_code == 404
    client = login(env, owner)
    for action in ("confirm", "dismiss"):
        denied = client.post(f"/applications/{card.id}/{action}", headers={CSRF: ""})
        assert denied.status_code in (400, 403)
    assert env.db.get(Application, card.id).dismissed_at is None  # type: ignore[union-attr]


def test_ac_old_mail_re_read_later_does_not_revive_a_dismissed_card(db_session: Session) -> None:
    user = user_of(db_session)
    card = review_card(db_session, user)
    dismissed = T0 + timedelta(days=2)
    svc.dismiss_review(db_session, user.id, card.id, dismissed)
    thread = thread_of(db_session, user, "t1")
    for sent in (T0, dismissed):  # older than, and exactly at, the dismissal
        again = svc.record_classification(
            db_session,
            user.id,
            thread,
            decisive(Label.INTERVIEW),
            Extracted(None, None, None, None),
            dismissed + timedelta(days=1),
            "m-old",
            sent,
        )
        assert again is not None and again.dismissed_at is not None and again.needs_review
