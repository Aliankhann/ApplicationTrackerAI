import pytest
from fastapi import APIRouter, FastAPI

from app.api.deps import PUBLIC_ROUTES
from app.cli import main as cli_main
from tests.routes import state_changing_routes
from tests.test_sessions import Env, cookies, env  # noqa: F401


def test_public_routes_exist_and_are_only_the_unsubscribe_routes() -> None:
    from tests.routes import all_routes

    assert set(PUBLIC_ROUTES) <= set(all_routes())
    assert {path for _, path in PUBLIC_ROUTES} == {"/unsubscribe"}
    assert ("POST", "/unsubscribe") not in state_changing_routes()


def test_state_changing_routes_are_enumerated() -> None:
    routes = state_changing_routes()
    assert ("POST", "/auth/logout") in routes
    assert any(m == "PATCH" and p.startswith("/applications/") for m, p in routes)


@pytest.mark.parametrize(("method", "path"), state_changing_routes())
def test_state_changing_route_requires_matching_csrf_header(
    env: Env,  # noqa: F811
    method: str,
    path: str,
) -> None:
    client = env.app()
    assert (
        client.request(method, path).status_code == 401
    )  # no session: 401 before CSRF; unprotected routes fail here
    raw, csrf, _ = env.login(env.user())
    other = env.login(env.user())[1]
    cookies(client, raw, csrf)
    for headers in ({}, {"X-CSRF-Token": "wrong"}, {"X-CSRF-Token": other}):
        response = client.request(method, path, headers=headers)
        assert response.status_code == 403
        assert response.json() == {"detail": "csrf_failed"}
    client.cookies.set("tracker_csrf", "tampered")  # cookie must match too
    assert client.request(method, path, headers={"X-CSRF-Token": csrf}).status_code == 403
    client.cookies.set("tracker_csrf", csrf)
    passed = client.request(method, path, headers={"X-CSRF-Token": csrf})
    assert passed.status_code not in (401, 403)  # CSRF cleared; the handler may still 404/422


def test_disallowed_origin_on_state_change_is_rejected_and_gets_no_cors_headers(
    env: Env,  # noqa: F811
) -> None:
    raw, csrf, _ = env.login(env.user())
    client = env.app()
    cookies(client, raw, csrf)
    evil = {"Origin": "https://evil.example", "X-CSRF-Token": csrf}
    response = client.post("/auth/logout", headers=evil)
    assert response.status_code == 403
    assert response.json() == {"detail": "origin_rejected"}
    assert "access-control-allow-origin" not in response.headers
    preflight = client.options(
        "/auth/logout",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in preflight.headers
    good = {"Origin": "http://localhost:5173", "X-CSRF-Token": csrf}
    ok = client.post("/auth/logout", headers=good)
    assert ok.status_code == 204
    assert ok.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert ok.headers["access-control-allow-credentials"] == "true"


def test_cli_session_create_refuses_outside_local(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("SESSION_SECRET", "y" * 40)
    get_settings.cache_clear()
    assert cli_main(["session", "create", "--email", "a@example.test"]) == 1
    assert "local" in capsys.readouterr().err


def test_cli_session_create_in_local_prints_cookie(
    env: Env,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    from contextlib import nullcontext

    env.app()
    assert (
        cli_main(["session", "create", "--email", "a@example.test"], lambda: nullcontext(env.db))
        == 0
    )
    assert "tracker_session=" in capsys.readouterr().out


def test_hidden_unprotected_route_is_csrf_protected_by_default(env: Env) -> None:  # noqa: F811
    assert {("GET", "/unsubscribe"), ("POST", "/unsubscribe")} == PUBLIC_ROUTES
    client = env.app()
    app = client.app
    assert isinstance(app, FastAPI)
    router = APIRouter()

    @router.post("/hidden", include_in_schema=False)
    def hidden() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(router)
    assert ("POST", "/hidden") in state_changing_routes(app)
    assert client.post("/hidden").status_code == 401
    raw, csrf, _ = env.login(env.user())
    cookies(client, raw, csrf)
    assert client.post("/hidden").status_code == 403
    assert client.post("/hidden", headers={"X-CSRF-Token": csrf}).status_code == 200
