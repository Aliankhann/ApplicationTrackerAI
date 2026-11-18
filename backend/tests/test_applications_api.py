import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.models import Application, EmailThread, User
from app.providers.classifier.types import ClassificationResult, Label
from app.providers.gmail.types import MessageMeta, ThreadMeta
from app.repositories import threads as threads_repo
from app.services import applications as svc
from app.services.extraction import Extracted
from tests.test_sessions import Env, cookies, env  # noqa: F401

CSRF = "X-CSRF-Token"


def make_app(
    env: Env,  # noqa: F811
    user: User,
    *,
    label: Label = Label.CONFIRMATION,
    from_user: bool = False,
    activity: datetime | None = None,
    company: str | None = "Acme",
    role: str | None = "Intern",
    subject: str = "Subject",
    snippet: str = "snip",
) -> Application:
    at = activity or env.clock.now
    gid = uuid.uuid4().hex[:16]
    message = MessageMeta(
        message_id=gid,
        thread_id=gid,
        from_address="jobs@acme.example",
        from_name="Acme",
        subject=subject,
        snippet=snippet,
        sent_at=at,
        from_user=from_user,
        rfc822_message_id=None,
        label_ids=frozenset(),
    )
    thread = threads_repo.upsert_thread(
        env.db, user.id, ThreadMeta(gid, "h", (message,)), subject, "acme.example", snippet
    )
    res = ClassificationResult(label, 0.9, "rules", "r1", False)
    application = svc.record_classification(
        env.db, user.id, thread, res, Extracted(company, role, "s", "s"), at
    )
    assert application is not None
    return application


def login(env: Env, user: User) -> TestClient:  # noqa: F811
    client = env.app()
    raw, csrf, _ = env.login(user)
    cookies(client, raw, csrf)
    client.headers[CSRF] = csrf
    return client


def thread_of(env: Env, application: Application) -> EmailThread:  # noqa: F811
    thread = env.db.get(EmailThread, application.source_thread_id)
    assert thread is not None
    return thread


def ids(response_json: dict[str, list[dict[str, str]]]) -> set[str]:
    return {item["id"] for item in response_json["items"]}


def test_ac1_list_filters_by_status_including_ghosted_with_fake_clock(env: Env) -> None:  # noqa: F811
    user = env.user()
    now = env.clock.now
    old, recent = now - timedelta(days=30), now - timedelta(days=5)
    ghost_applied = make_app(env, user, from_user=True, activity=old)
    ghost_oa = make_app(env, user, label=Label.ONLINE_ASSESSMENT, from_user=True, activity=old)
    replied = make_app(env, user, from_user=False, activity=old)
    recent_sent = make_app(env, user, from_user=True, activity=recent)
    interview = make_app(env, user, label=Label.INTERVIEW, from_user=True, activity=old)
    client = login(env, user)

    def listed(status: str) -> set[str]:
        response = client.get("/applications", params={"status": status})
        assert response.status_code == 200
        return ids(response.json())

    assert listed("ghosted") == {str(ghost_applied.id), str(ghost_oa.id)}
    assert listed("applied") == {str(replied.id), str(recent_sent.id)}
    assert listed("interview") == {str(interview.id)}
    assert listed("offer") == set()
    body = client.get("/applications").json()
    shown = {i["id"]: i["display_status"] for i in body["items"]}
    assert shown[str(ghost_applied.id)] == "ghosted"
    assert shown[str(interview.id)] == "interview"
    env.clock.now = now + timedelta(days=30)  # the clock moves: the recent one turns ghosted
    client = login(env, user)  # the old session idled out
    assert str(recent_sent.id) in listed("ghosted")
    assert client.get("/applications", params={"status": "bogus"}).status_code == 422


def test_ac1_list_sorts_by_last_activity_or_applied_at_in_either_order(env: Env) -> None:  # noqa: F811
    user = env.user()
    now = env.clock.now
    first = make_app(env, user, activity=now - timedelta(days=3))
    second = make_app(env, user, activity=now - timedelta(days=2))
    third = make_app(env, user, activity=now - timedelta(days=1))
    first.last_activity_at = now  # activity order differs from applied_at order
    env.db.flush()
    client = login(env, user)

    def order(**params: str) -> list[str]:
        return [i["id"] for i in client.get("/applications", params=params).json()["items"]]

    a, b, c = str(first.id), str(second.id), str(third.id)
    assert order() == [a, c, b]
    assert order(order="asc") == [b, c, a]
    assert order(sort="applied_at") == [c, b, a]
    assert order(sort="applied_at", order="asc") == [a, b, c]


@pytest.mark.parametrize(
    ("sort", "order"),
    [("last_activity", "desc"), ("last_activity", "asc"), ("applied_at", "desc")],
)
def test_ac1_pagination_is_stable_with_ties_no_dupes_no_gaps(
    env: Env,  # noqa: F811
    sort: str,
    order: str,
) -> None:
    user = env.user()
    tied = env.clock.now
    made = {str(make_app(env, user, activity=tied).id) for _ in range(7)}
    made.add(str(make_app(env, user, activity=tied - timedelta(days=1)).id))
    client = login(env, user)
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(10):
        params = {"sort": sort, "order": order, "limit": "3"}
        if cursor:
            params["cursor"] = cursor
        body = client.get("/applications", params=params).json()
        seen += [i["id"] for i in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == 8
    assert set(seen) == made


def test_ac1_applied_at_sort_pages_over_null_applied_at(env: Env) -> None:  # noqa: F811
    user = env.user()
    for _ in range(3):
        make_app(env, user, label=Label.INTERVIEW)  # no applied_at
    make_app(env, user)
    client = login(env, user)
    first = client.get("/applications", params={"sort": "applied_at", "limit": "2"}).json()
    rest = client.get(
        "/applications",
        params={"sort": "applied_at", "limit": "2", "cursor": first["next_cursor"]},
    ).json()
    assert len(ids(first) | ids(rest)) == 4 and rest["next_cursor"] is None


def test_ac1_bad_cursor_is_400_and_limit_is_bounded(env: Env) -> None:  # noqa: F811
    import base64

    client = login(env, env.user())
    good_shape = base64.urlsafe_b64encode(
        f"last_activity|2026-01-01T00:00:00|{uuid.uuid4()}".encode()
    )
    wrong_sort = base64.urlsafe_b64encode(
        f"applied_at|2026-01-01T00:00:00+00:00|{uuid.uuid4()}".encode()
    )
    for bad in ("!!!", "abc", good_shape.decode(), wrong_sort.decode(), ""):
        response = client.get("/applications", params={"cursor": bad})
        if bad == "":
            assert response.status_code == 200
        else:
            assert response.status_code == 400, bad
    for limit in ("0", "101"):
        assert client.get("/applications", params={"limit": limit}).status_code == 422


def test_ac2_detail_returns_subject_snippet_only_to_owner_and_events_ordered(
    env: Env,  # noqa: F811
) -> None:
    owner, other = env.user(), env.user()
    application = make_app(env, owner, subject="Hi <b>there</b>", snippet="a <script>")
    client = login(env, owner)
    body = client.get(f"/applications/{application.id}").json()
    assert body["subject"] == "Hi <b>there</b>" and body["snippet"] == "a <script>"
    assert body["company"] == "Acme" and body["needs_review"] is False
    client.patch(f"/applications/{application.id}", json={"status": "offer"})
    events = client.get(f"/applications/{application.id}/events").json()
    assert [(e["from_status"], e["to_status"], e["reason"]) for e in events] == [
        (None, "applied", "created"),
        ("applied", "offer", "manual"),
    ]
    stranger = login(env, other)
    for path in (f"/applications/{application.id}", f"/applications/{application.id}/events"):
        assert stranger.get(path).status_code == 404
    assert stranger.get(f"/applications/{uuid.uuid4()}").status_code == 404
    assert "Acme" not in stranger.get("/applications").text


def test_ac2_needs_review_reflects_latest_classification(env: Env) -> None:  # noqa: F811
    user = env.user()
    application = make_app(env, user)
    client = login(env, user)
    assert client.get(f"/applications/{application.id}").json()["needs_review"] is False
    review = ClassificationResult(None, 0.4, "rules", None, True)
    svc.record_classification(
        env.db,
        user.id,
        thread_of(env, application),
        review,
        Extracted(None, None, None, None),
        env.clock.now,
    )
    assert client.get(f"/applications/{application.id}").json()["needs_review"] is True


def test_ac3_patch_status_locks_writes_manual_event_and_classifier_cannot_override(
    env: Env,  # noqa: F811
) -> None:
    user = env.user()
    application = make_app(env, user)
    client = login(env, user)
    response = client.patch(f"/applications/{application.id}", json={"status": "interview"})
    assert response.status_code == 200
    assert response.json()["status"] == "interview" and response.json()["status_locked"] is True
    later = env.clock.now + timedelta(days=1)
    rejection = ClassificationResult(Label.REJECTION, 0.95, "rules", "rej", False)
    svc.record_classification(
        env.db,
        user.id,
        thread_of(env, application),
        rejection,
        Extracted(None, None, None, None),
        later,
    )
    assert client.get(f"/applications/{application.id}").json()["status"] == "interview"
    reasons = [e["reason"] for e in client.get(f"/applications/{application.id}/events").json()]
    assert reasons == ["created", "manual"]


def test_ac3_company_role_edits_persist_and_later_sync_does_not_overwrite(
    env: Env,  # noqa: F811
) -> None:
    user = env.user()
    application = make_app(env, user, company=None, role=None)
    client = login(env, user)
    body = client.patch(
        f"/applications/{application.id}",
        json={"company": "Mine Co", "role": "Dev", "followups_paused": True},
    ).json()
    assert (body["company"], body["role"], body["followups_paused"]) == ("Mine Co", "Dev", True)
    assert body["status_locked"] is False
    interview = ClassificationResult(Label.INTERVIEW, 0.9, "rules", "i", False)
    svc.record_classification(
        env.db,
        user.id,
        thread_of(env, application),
        interview,
        Extracted("Other", "Different", "s", "s"),
        env.clock.now + timedelta(hours=1),
    )
    again = client.get(f"/applications/{application.id}").json()
    assert (again["company"], again["role"], again["status"]) == ("Mine Co", "Dev", "interview")


def test_ac4_patch_rejects_extra_empty_null_and_too_long_fields(env: Env) -> None:  # noqa: F811
    user = env.user()
    application = make_app(env, user)
    client = login(env, user)
    url = f"/applications/{application.id}"
    bad_bodies: list[dict[str, object]] = [
        {"user_id": str(uuid.uuid4())},
        {"status_locked": False},
        {"company": ""},
        {"company": "x" * 81},
        {"role": "y" * 121},
        {"company": "‮​"},
        {"company": None},
        {"status": "ghosted"},
        {"status": None},
    ]
    for body in bad_bodies:
        assert client.patch(url, json=body).status_code == 422, body
    assert client.patch("/applications/not-a-uuid", json={}).status_code == 422
    assert client.get(url).json()["company"] == "Acme"


def test_ac4_patch_strips_bidi_and_zero_width_characters(env: Env) -> None:  # noqa: F811
    user = env.user()
    application = make_app(env, user)
    client = login(env, user)
    body = client.patch(
        f"/applications/{application.id}",
        json={"company": "  Ac‮me​ ", "role": "In⁦tern"},
    ).json()
    assert (body["company"], body["role"]) == ("Acme", "Intern")
