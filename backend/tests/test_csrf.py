import re
import uuid
from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI

from app.api.deps import PUBLIC_ROUTES
from app.cli import main as cli_main
from app.main import app as real_app
from tests.test_sessions import Env, cookies, env  # noqa: F401

STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}


def walk(routes: Sequence[Any], prefix: str = "") -> Iterator[tuple[str, str]]:
    """Yield (METHOD, path) for every route, including hidden ones and wrapped included routers."""
    for route in routes:
        if hasattr(route, "original_router"):  # fastapi's wrapped included router
            inner = prefix + route.include_context.prefix
            yield from walk(route.original_router.routes, inner)
        elif getattr(route, "methods", None):
            for method in route.methods:
                yield method, prefix + route.path


def state_changing_routes(app: FastAPI = real_app) -> list[tuple[str, str]]:
    return sorted(
        (method, re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path))
        for method, path in walk(app.routes)
        if method in STATE_CHANGING and (method, path) not in PUBLIC_ROUTES
    )


def test_state_changing_routes_are_enumerated() -> None:
    assert ("POST", "/auth/logout") in state_changing_routes()


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
    assert client.request(method, path, headers={"X-CSRF-Token": csrf}).status_code < 300


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
    assert frozenset() == PUBLIC_ROUTES
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
