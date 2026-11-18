"""US-66: follow-up queue routes."""

from datetime import timedelta

from sqlalchemy import select

from app.models import FollowUpTask
from app.repositories import followups as repo
from app.repositories import sequences as sequences_repo
from tests.test_applications_api import login, make_app
from tests.test_sessions import Env, env  # noqa: F401


def add_task(env: Env, user, application, step: int, days: float, state: str = "pending"):  # type: ignore[no-untyped-def]  # noqa: F811
    seq = sequences_repo.get_or_create_default(env.db, user.id)
    due = env.clock.now + timedelta(days=days)
    repo.insert_if_absent(env.db, application.id, seq.id, step, due, env.clock.now, state=state)
    return env.db.scalars(
        select(FollowUpTask).where(
            FollowUpTask.application_id == application.id, FollowUpTask.step_index == step
        )
    ).one()


def test_list_defaults_to_pending_and_drafted_ordered_by_due_at(env: Env) -> None:  # noqa: F811
    user = env.user()
    a, b, c = (make_app(env, user, company=n, from_user=True) for n in "ABC")
    late = add_task(env, user, a, 0, 9)
    soon = add_task(env, user, b, 0, 2, "drafted")
    add_task(env, user, c, 0, 1, "sent")
    client = login(env, user)
    items = client.get("/follow-ups").json()
    assert [i["id"] for i in items] == [str(soon.id), str(late.id)]
    assert items[0]["can_skip"] is False and items[1]["can_skip"] is True
    assert items[1]["company"] == "A" and items[1]["cancel_reason"] is None


def test_list_state_filter(env: Env) -> None:  # noqa: F811
    user = env.user()
    a, b = make_app(env, user, from_user=True), make_app(env, user, from_user=True)
    add_task(env, user, a, 0, 3)
    add_task(env, user, b, 0, 4, "drafted")
    client = login(env, user)
    assert [i["state"] for i in client.get("/follow-ups?state=pending").json()] == ["pending"]
    assert [i["state"] for i in client.get("/follow-ups?state=drafted").json()] == ["drafted"]
    assert len(client.get("/follow-ups?state=all").json()) == 2
    assert client.get("/follow-ups?state=bogus").status_code == 422


def test_skip_pending_sets_skipped_with_reason(env: Env) -> None:  # noqa: F811
    user = env.user()
    task = add_task(env, user, make_app(env, user, from_user=True), 0, 3)
    response = login(env, user).post(f"/follow-ups/{task.id}/skip")
    assert response.status_code == 200
    assert response.json()["state"] == "skipped"
    assert response.json()["cancel_reason"] == "user_skipped"


def test_skip_conflicts_when_scheduler_holds_task_in_drafting(env: Env) -> None:  # noqa: F811
    user = env.user()
    task = add_task(env, user, make_app(env, user, from_user=True), 0, -1)
    assert repo.claim_task(env.db, task.id, env.clock.now)  # scheduler claims it
    response = login(env, user).post(f"/follow-ups/{task.id}/skip")
    assert response.status_code == 409
    env.db.expire_all()
    assert env.db.get(FollowUpTask, task.id).state == "drafting"  # type: ignore[union-attr]


def test_skip_and_delay_conflict_for_drafted_and_already_skipped(env: Env) -> None:  # noqa: F811
    user = env.user()
    a, b = make_app(env, user, from_user=True), make_app(env, user, from_user=True)
    drafted = add_task(env, user, a, 0, 1, "drafted")
    skipped = add_task(env, user, b, 0, 1)
    client = login(env, user)
    assert client.post(f"/follow-ups/{skipped.id}/skip").status_code == 200
    assert client.post(f"/follow-ups/{skipped.id}/skip").status_code == 409
    assert client.post(f"/follow-ups/{drafted.id}/skip").status_code == 409
    assert client.post(f"/follow-ups/{drafted.id}/delay", json={"days": 3}).status_code == 409


def test_delay_moves_only_that_task_later(env: Env) -> None:  # noqa: F811
    user = env.user()
    a = make_app(env, user, from_user=True)
    first, second = add_task(env, user, a, 0, 3), add_task(env, user, a, 1, 10)
    before = second.due_at
    response = login(env, user).post(f"/follow-ups/{first.id}/delay", json={"days": 3})
    assert response.status_code == 200
    env.db.expire_all()
    assert env.db.get(FollowUpTask, first.id).due_at == env.clock.now + timedelta(days=6)  # type: ignore[union-attr]
    assert env.db.get(FollowUpTask, second.id).due_at == before  # type: ignore[union-attr]


def test_delay_rejects_days_outside_1_to_30(env: Env) -> None:  # noqa: F811
    user = env.user()
    task = add_task(env, user, make_app(env, user, from_user=True), 0, 3)
    client = login(env, user)
    for days in (0, 31, -1):
        assert client.post(f"/follow-ups/{task.id}/delay", json={"days": days}).status_code == 422


def test_other_users_task_is_404_and_unchanged(env: Env) -> None:  # noqa: F811
    owner, other = env.user(), env.user()
    task = add_task(env, owner, make_app(env, owner, from_user=True), 0, 3)
    client = login(env, other)
    assert client.post(f"/follow-ups/{task.id}/skip").status_code == 404
    assert client.post(f"/follow-ups/{task.id}/delay", json={"days": 2}).status_code == 404
    assert client.get("/follow-ups").json() == []
    env.db.expire_all()
    assert env.db.get(FollowUpTask, task.id).state == "pending"  # type: ignore[union-attr]
