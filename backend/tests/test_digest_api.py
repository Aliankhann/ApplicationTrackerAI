"""US-72 unsubscribe link and the settings toggle."""

import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.jobs.digest import unsubscribe_url
from app.models import User
from app.security.unsubscribe import create_token, verify_token
from tests.test_applications_api import login, thread_of  # noqa: F401
from tests.test_sessions import Env, cookies, env  # noqa: F401

MAX_AGE = timedelta(days=60)
ONE_CLICK = {"Content-Type": "application/x-www-form-urlencoded"}


def secret() -> str:
    return get_settings().session_secret.get_secret_value()


def enabled(env: Env, user: User) -> bool:  # noqa: F811
    env.db.refresh(user)
    return user.digest_enabled


def link_token(env: Env, user: User) -> str:  # noqa: F811
    return create_token(secret(), user.id, env.clock.now)


def test_us72_get_shows_confirmation_and_changes_nothing(env: Env) -> None:  # noqa: F811
    user = env.user()
    client = env.app()
    token = link_token(env, user)
    response = client.get("/unsubscribe", params={"token": token})
    assert response.status_code == 200
    assert 'method="post"' in response.text and token in response.text
    assert "<script" not in response.text
    assert enabled(env, user) is True
    assert "form-action 'self'" in response.headers["content-security-policy"]


def test_us72_post_with_form_turns_digest_off_without_a_session_and_is_idempotent(
    env: Env,  # noqa: F811
) -> None:
    user = env.user()
    client = env.app()
    token = link_token(env, user)
    for _ in range(2):
        response = client.post("/unsubscribe", data={"token": token})
        assert response.status_code == 200 and "unsubscribed" in response.text
        assert enabled(env, user) is False


def test_us72_post_with_json_body_works(env: Env) -> None:  # noqa: F811
    user = env.user()
    response = env.app().post("/unsubscribe", json={"token": link_token(env, user)})
    assert response.status_code == 200 and enabled(env, user) is False


def test_us72_rfc8058_one_click_post_to_the_header_url_works(env: Env) -> None:  # noqa: F811
    user = env.user()
    client = env.app()
    url = unsubscribe_url(get_settings(), user.id, env.clock.now)
    path = url.removeprefix(get_settings().api_base_url)
    response = client.post(path, content="List-Unsubscribe=One-Click", headers=ONE_CLICK)
    assert response.status_code == 200 and enabled(env, user) is False


def test_us72_post_from_the_confirmation_page_origin_is_allowed(env: Env) -> None:  # noqa: F811
    user = env.user()
    response = env.app().post(
        "/unsubscribe",
        data={"token": link_token(env, user)},
        headers={"Origin": "http://localhost:8000"},
    )
    assert response.status_code == 200 and enabled(env, user) is False


def test_us72_tampered_expired_missing_and_foreign_tokens_are_all_the_same_400(
    env: Env,  # noqa: F811
) -> None:
    user = env.user()
    client = env.app()
    good = link_token(env, user)
    uid, issued, mac = good.split(".")
    other = env.user()
    bad = [
        "",
        "garbage",
        good[:-2] + "AA",
        f"{uid}.{int(issued) + 1}.{mac}",
        f"{other.id.hex}.{issued}.{mac}",
        f"{uid}.99999999999999999999.{mac}",
        create_token("y" * 40, user.id, env.clock.now),
    ]
    env.clock.now += MAX_AGE + timedelta(seconds=1)
    bad.append(good)  # expired
    bodies = set()
    for token in bad:
        for response in (
            client.get("/unsubscribe", params={"token": token}),
            client.post("/unsubscribe", data={"token": token}),
        ):
            assert response.status_code == 400
            bodies.add(response.text)
    assert len(bodies) == 1
    assert client.get("/unsubscribe").status_code == 400
    assert client.post("/unsubscribe").status_code == 400
    assert enabled(env, user) is True and enabled(env, other) is True


def test_us72_token_just_inside_expiry_still_works(env: Env) -> None:  # noqa: F811
    user = env.user()
    token = link_token(env, user)
    env.clock.now += MAX_AGE - timedelta(seconds=1)
    assert env.app().post("/unsubscribe", data={"token": token}).status_code == 200


def test_us72_token_is_bound_to_its_purpose_key() -> None:
    from datetime import UTC, datetime

    now = datetime(2026, 1, 1, tzinfo=UTC)
    uid = uuid.uuid4()
    token = create_token("s" * 40, uid, now)
    assert verify_token("s" * 40, token, now, MAX_AGE) == uid
    assert verify_token("t" * 40, token, now, MAX_AGE) is None
    assert verify_token("s" * 40, token, now - timedelta(hours=1), MAX_AGE) is None  # future


def test_us72_unsubscribing_a_deleted_user_is_a_quiet_200(env: Env) -> None:  # noqa: F811
    token = create_token(secret(), uuid.uuid4(), env.clock.now)
    assert env.app().post("/unsubscribe", data={"token": token}).status_code == 200


def test_us72_oversized_body_is_rejected(env: Env) -> None:  # noqa: F811
    response = env.app().post("/unsubscribe", content="token=" + "a" * 5000, headers=ONE_CLICK)
    assert response.status_code == 400


# ---------- settings toggle ----------


def test_us72_settings_get_and_patch_toggle_for_the_session_user_only(env: Env) -> None:  # noqa: F811
    a, b = env.user(), env.user()
    client = login(env, a)
    assert client.get("/settings").json() == {"digest_enabled": True}
    response = client.patch("/settings", json={"digest_enabled": False})
    assert response.status_code == 200 and response.json() == {"digest_enabled": False}
    assert enabled(env, a) is False and enabled(env, b) is True
    assert client.get("/settings").json() == {"digest_enabled": False}
    assert client.patch("/settings", json={"digest_enabled": True}).json() == {
        "digest_enabled": True
    }


def test_us72_settings_validation_and_auth(env: Env) -> None:  # noqa: F811
    user = env.user()
    client = login(env, user)
    assert client.patch("/settings", json={}).status_code == 422
    assert client.patch("/settings", json={"digest_enabled": "x"}).status_code == 422
    assert client.patch("/settings", json={"digest_enabled": True, "x": 1}).status_code == 422
    anon = env.app()
    assert anon.get("/settings").status_code == 401
    assert anon.patch("/settings", json={"digest_enabled": False}).status_code == 401


def test_us72_settings_patch_requires_csrf(env: Env) -> None:  # noqa: F811
    user = env.user()
    client: TestClient = env.app()
    raw, csrf, _ = env.login(user)
    cookies(client, raw, csrf)
    response = client.patch("/settings", json={"digest_enabled": False})
    assert response.status_code == 403
    assert enabled(env, user) is True


def test_us71_api_base_url_must_be_public_https_outside_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import ConfigError, Settings

    monkeypatch.setenv("SESSION_SECRET", "k" * 40)
    monkeypatch.delenv("API_BASE_URL")
    ok = "https://api.example.test"
    assert Settings(environment="prod", api_base_url=ok).api_base_url == ok
    for bad in ("http://api.example.test", "https://localhost:8000", "http://localhost:8000", ""):
        with pytest.raises(ConfigError):
            Settings(environment="staging", api_base_url=bad)
    assert Settings(environment="local").api_base_url.startswith("http://localhost")
