"""US-61 routes: sequences API and preview."""

from typing import Any

from sqlalchemy import func, select

from app.models import Sequence
from tests.test_applications_api import login
from tests.test_sessions import Env, env  # noqa: F401

STEPS = [{"delay_days": 5, "template": "Hello about {role} at {company}", "max_attempts": 1}]


def body(**over: Any) -> dict[str, Any]:
    return {"name": "Mine", "steps": STEPS, "tone": "warm", "make_default": False, **over}


def fields(response: Any) -> dict[str, str]:
    return {e["field"]: e["code"] for e in response.json()["detail"]}


def test_list_creates_default_on_first_use(env: Env) -> None:  # noqa: F811
    client = login(env, env.user())
    items = client.get("/sequences").json()
    assert len(items) == 1 and items[0]["is_default"] is True
    assert [s["delay_days"] for s in items[0]["steps"]] == [7, 14]
    assert len(client.get("/sequences").json()) == 1


def test_create_and_default_switching(env: Env) -> None:  # noqa: F811
    client = login(env, env.user())
    first = client.get("/sequences").json()[0]
    created = client.post("/sequences", json=body(make_default=True))
    assert created.status_code == 201 and created.json()["is_default"] is True
    listed = {s["id"]: s["is_default"] for s in client.get("/sequences").json()}
    assert listed[first["id"]] is False
    back = client.patch(f"/sequences/{first['id']}", json={"make_default": True})
    assert back.json()["is_default"] is True
    assert sum(s["is_default"] for s in client.get("/sequences").json()) == 1


def test_patch_updates_fields_and_cannot_unset_only_default(env: Env) -> None:  # noqa: F811
    client = login(env, env.user())
    seq = client.get("/sequences").json()[0]
    out = client.patch(
        f"/sequences/{seq['id']}", json={"name": "New", "tone": "formal", "steps": STEPS}
    ).json()
    assert (out["name"], out["tone"], len(out["steps"])) == ("New", "formal", 1)
    response = client.patch(f"/sequences/{seq['id']}", json={"make_default": False})
    assert response.status_code == 422
    assert fields(response) == {"make_default": "invalid_operation"}


def test_crlf_in_templates_is_normalized(env: Env) -> None:  # noqa: F811
    client = login(env, env.user())
    steps = [{**STEPS[0], "template": "Line one\r\nLine two {role}"}]
    out = client.post("/sequences", json=body(steps=steps)).json()
    assert out["steps"][0]["template"] == "Line one\nLine two {role}"


def test_validation_errors_are_422_with_field_level_codes(env: Env) -> None:  # noqa: F811
    client = login(env, env.user())
    bad_steps = [
        {"delay_days": 10, "template": "ok"},
        {"delay_days": 5, "template": "Hi {bogus}"},
        {"delay_days": 99, "template": "x"},
    ]
    response = client.post("/sequences", json=body(name="  ", tone="loud", steps=bad_steps))
    assert response.status_code == 422
    got = fields(response)
    assert got["name"] == "invalid_name" and got["tone"] == "invalid_tone"
    assert got["steps.1.template"] == "invalid_template"
    assert got["steps.2.delay_days"] == "less_than_equal"
    delays = client.post("/sequences", json=body(steps=[*bad_steps[:1], {**STEPS[0]}]))
    assert fields(delays) == {"steps": "delays_not_increasing"}
    assert client.post("/sequences", json=body(steps=[])).status_code == 422
    too_many = [{"delay_days": d, "template": "x"} for d in range(1, 7)]
    assert client.post("/sequences", json=body(steps=too_many)).status_code == 422


def test_other_users_sequence_is_404_and_not_listed(env: Env) -> None:  # noqa: F811
    owner, other = env.user(), env.user()
    mine = login(env, owner).get("/sequences").json()[0]
    client = login(env, other)
    assert client.patch(f"/sequences/{mine['id']}", json={"name": "x"}).status_code == 404
    assert mine["id"] not in [s["id"] for s in client.get("/sequences").json()]


def test_preview_renders_sample_data_and_writes_nothing(env: Env) -> None:  # noqa: F811
    client = login(env, env.user())
    before = env.db.scalar(select(func.count()).select_from(Sequence))
    out = client.post("/sequences/preview", json={"template": "About {role}", "tone": "formal"})
    assert out.status_code == 200
    assert out.json()["text"].startswith("Dear Alex,")
    assert "Software Engineering Intern" in out.json()["text"]
    assert env.db.scalar(select(func.count()).select_from(Sequence)) == before
    bad = client.post("/sequences/preview", json={"template": "{nope}"})
    assert bad.status_code == 422 and fields(bad) == {"template": "invalid_template"}


def test_removing_steps_cancels_out_of_range_pending_tasks(env: Env) -> None:  # noqa: F811
    from datetime import timedelta

    from app.models import FollowUpTask
    from app.repositories import followups as followups_repo
    from tests.test_applications_api import make_app

    user = env.user()
    client = login(env, user)
    seq = client.get("/sequences").json()[0]
    application = make_app(env, user, from_user=True)
    due = env.clock.now + timedelta(days=5)
    for step in (0, 1):
        followups_repo.insert_if_absent(env.db, application.id, seq["id"], step, due, env.clock.now)
    assert client.patch(f"/sequences/{seq['id']}", json={"steps": STEPS}).status_code == 200
    states = {
        t.step_index: (t.state, t.cancel_reason)
        for t in env.db.scalars(
            select(FollowUpTask).where(FollowUpTask.application_id == application.id)
        )
    }
    assert states == {0: ("pending", None), 1: ("cancelled", "step_removed")}


def test_removing_steps_leaves_other_sequences_tasks_alone(env: Env) -> None:  # noqa: F811
    from datetime import timedelta

    from app.models import FollowUpTask
    from app.repositories import followups as followups_repo
    from tests.test_applications_api import make_app

    user = env.user()
    client = login(env, user)
    default = client.get("/sequences").json()[0]
    other = client.post(
        "/sequences", json={"name": "Other", "steps": default["steps"], "tone": "short"}
    )
    assert other.status_code in (200, 201), other.text
    application = make_app(env, user, from_user=True)
    due = env.clock.now + timedelta(days=5)
    followups_repo.insert_if_absent(
        env.db, application.id, other.json()["id"], 1, due, env.clock.now
    )
    assert client.patch(f"/sequences/{default['id']}", json={"steps": STEPS}).status_code == 200
    task = env.db.scalars(
        select(FollowUpTask).where(FollowUpTask.application_id == application.id)
    ).one()
    assert (task.state, task.cancel_reason) == ("pending", None)
