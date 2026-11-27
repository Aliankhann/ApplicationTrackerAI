import base64
from datetime import timedelta
from typing import Any

import pytest

from app.api.applications import encode_cursor
from app.config import get_settings
from app.models import Application
from tests.test_applications_api import CSRF, login, make_app
from tests.test_sessions import Env, env  # noqa: F401


def test_ac1_cursor_from_other_users_row_leaks_nothing(env: Env) -> None:  # noqa: F811
    a, b = env.user(), env.user()
    secret = make_app(env, a, company="AlphaSecret")
    mine = make_app(env, b, company="Mine")
    c = login(env, b)
    cur = encode_cursor("last_activity", secret.last_activity_at + timedelta(days=1), secret.id)
    r = c.get("/applications", params={"cursor": cur})
    assert r.status_code == 200
    assert "AlphaSecret" not in r.text and str(secret.id) not in r.text
    assert str(mine.id) in r.text


@pytest.mark.parametrize(
    "params",
    [
        {"sort": "applied_at; drop table users"},
        {"order": "desc,id"},
        {"limit": 0},
        {"limit": -1},
        {"limit": 101},
        {"limit": 99999999999999999999},
        {"status": "ghosted' OR 1=1"},
        {"cursor": "x" * 301},
    ],
)
def test_ac1_bad_params_rejected(env: Env, params: dict[str, Any]) -> None:  # noqa: F811
    c = login(env, env.user())
    assert c.get("/applications", params=params).status_code == 422


def test_ac1_cursor_variants_never_500(env: Env) -> None:  # noqa: F811
    c = login(env, env.user())
    good = "last_activity|2026-01-01T00:00:00+00:00|" + "0" * 32
    for raw in [
        "last_activity|2026-01-01T00:00:00|" + "0" * 32,
        "applied_at|2026-01-01T00:00:00+00:00|" + "0" * 32,
        "last_activity|0001-01-01T00:00:00+00:00|" + "0" * 32,
        "last_activity|9999-12-31T23:59:59+00:00|" + "0" * 32,
        good + "|x",
        "\xff",
    ]:
        cur = base64.urlsafe_b64encode(raw.encode("latin-1")).decode()
        r = c.get("/applications", params={"cursor": cur})
        assert r.status_code in (200, 400), (raw, r.status_code, r.text)
        assert r.status_code != 500


def test_ac1_ghosted_boundary_is_exclusive_at_configured_cutoff(env: Env) -> None:  # noqa: F811
    days = get_settings().ghosted_after_days
    u = env.user()
    cutoff = env.clock.now - timedelta(days=days)
    edge = make_app(env, u, from_user=True, activity=cutoff)
    past = make_app(env, u, from_user=True, activity=cutoff - timedelta(seconds=1))
    c = login(env, u)
    assert c.get(f"/applications/{edge.id}").json()["display_status"] == "applied"
    assert c.get(f"/applications/{past.id}").json()["display_status"] == "ghosted"
    listed = c.get("/applications", params={"status": "ghosted"}).json()
    assert {i["id"] for i in listed["items"]} == {str(past.id)}


def test_ac3_patch_requires_csrf_and_edits_persist(env: Env) -> None:  # noqa: F811
    u = env.user()
    app = make_app(env, u, company="Before")
    c = login(env, u)
    h = {CSRF: ""}
    assert c.patch(f"/applications/{app.id}", json={"company": "X"}, headers=h).status_code in (
        403,
        401,
    )
    r = c.patch(f"/applications/{app.id}", json={"status": "interview", "company": "After"})
    assert r.status_code == 200 and r.json()["status_locked"] is True
    r = c.patch(f"/applications/{app.id}", json={"status": "interview"})
    assert r.status_code == 200
    r = c.patch(f"/applications/{app.id}", json={"company": "‮​  \u0000"})
    assert r.status_code == 422
    r = c.patch(f"/applications/{app.id}", json={})
    assert r.status_code == 200
    env.db.expire_all()
    assert env.db.get(Application, app.id).company == "After"  # type: ignore[union-attr]
