import json
import logging
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.log import AllowlistJsonFormatter, configure_logging, get_logger
from app.main import create_app
from tests.test_sync import CLASSIFIER, NOW, fake, make_user

FORMATTER = AllowlistJsonFormatter()
SECRET = "sk-secret-value-123"  # noqa: S105


def render(record: logging.LogRecord) -> str:
    return FORMATTER.format(record)


def make_record() -> logging.LogRecord:
    return logging.LogRecord("t", logging.INFO, "f", 1, "evt.done", (), None)


def logged(caplog: pytest.LogCaptureFixture, name: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == name]


def test_log_with_disallowed_extras_emits_only_allowed_keys_and_dropped_names(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    get_logger("app.test").info(
        "sync.completed",
        extra={"mode": "initial", "user_id": uuid.uuid4(), "subject": SECRET, "token": SECRET},
    )
    output = render(caplog.records[-1])
    data = json.loads(output)
    assert set(data) == {"ts", "level", "logger", "event", "mode", "user_id", "dropped_fields"}
    assert isinstance(data["user_id"], str)
    assert data["dropped_fields"] == ["subject", "token"]
    assert SECRET not in output


def test_long_strings_in_allowed_fields_are_capped_at_200() -> None:
    record = make_record()
    record.path = "/" + "x" * 500
    data = json.loads(render(record))
    assert len(data["path"]) == 200


def test_exception_logs_exc_type_only() -> None:
    try:
        raise ValueError(SECRET)
    except ValueError:
        record = logging.LogRecord("t", logging.ERROR, "f", 1, "job.failed", (), sys.exc_info())
    output = render(record)
    assert json.loads(output)["exc_type"] == "ValueError"
    assert SECRET not in output and "Traceback" not in output


def test_event_never_interpolates_arguments() -> None:
    record = logging.LogRecord("t", logging.INFO, "f", 1, "q %s", (SECRET,), None)
    assert SECRET not in render(record)


def test_configure_logging_routes_third_party_through_formatter_and_disables_access_log(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(Settings(log_level="INFO"))
    logging.getLogger("uvicorn.error").info("started")
    logging.getLogger("sqlalchemy.engine").info("SELECT %s", SECRET)
    logging.getLogger("uvicorn.access").info("GET /?q=%s", SECRET)
    lines = capsys.readouterr().out.strip().splitlines()
    assert [json.loads(line)["logger"] for line in lines] == ["uvicorn.error"]
    assert logging.getLogger("uvicorn.access").disabled


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield TestClient(create_app())


def test_request_log_has_id_method_path_without_query_status_duration(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    response = client.get("/health?token=" + SECRET, headers={"Cookie": "s=" + SECRET})
    data = json.loads(render(logged(caplog, "app.request")[-1]))
    assert data["event"] == "http.request"
    assert data["method"] == "GET" and data["path"] == "/health" and data["status"] == 200
    assert data["request_id"] == response.headers["X-Request-ID"]
    assert isinstance(data["duration_ms"], float | int)
    assert SECRET not in json.dumps(data)
    assert uuid.UUID(response.headers["X-Request-ID"]).version == 4


def test_valid_inbound_request_id_is_kept_and_invalid_one_ignored(client: TestClient) -> None:
    good = str(uuid.uuid4())
    assert client.get("/health", headers={"X-Request-ID": good}).headers["X-Request-ID"] == good
    bad = client.get("/health", headers={"X-Request-ID": "not-a-uuid\r"}).headers["X-Request-ID"]
    assert bad != "not-a-uuid" and uuid.UUID(bad)


def test_sync_logs_counts_mode_and_error_code_without_content(
    db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    from app.providers.gmail import GmailError
    from app.services.sync import SyncFailed, run_sync

    caplog.set_level(logging.INFO)
    user_id = make_user(db_session)
    run_sync(db_session, user_id, fake(), CLASSIFIER, NOW, commit=db_session.flush)
    client = fake()
    client.fail_next(GmailError("secret subject text"))
    with pytest.raises(SyncFailed):
        run_sync(db_session, user_id, client, CLASSIFIER, NOW, commit=db_session.flush)
    completed, failed = (json.loads(render(r)) for r in logged(caplog, "app.sync"))
    assert completed["event"] == "sync.completed" and completed["mode"] == "initial"
    assert completed["threads_seen"] == 5 and completed["threads_kept"] == 4
    assert failed["event"] == "sync.failed" and failed["error_code"] == "gmail_error"
    everything = json.dumps([completed, failed])
    assert "Synthetic snippet" not in everything and "secret subject" not in everything
    assert "dropped_fields" not in completed and "dropped_fields" not in failed


EXPECTED = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-site",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
}


def app_for(environment: str, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setenv("ENVIRONMENT", environment)
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        return create_app()
    finally:
        get_settings.cache_clear()


def test_every_response_carries_security_headers_and_hsts_only_outside_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for environment in ("local", "prod"):
        client = TestClient(app_for(environment, monkeypatch))
        responses = [
            client.get("/health"),
            client.get("/nope"),
            client.get("/health", params={}, headers={"X-Request-ID": "x"}),
            client.post("/health"),
        ]
        for response in responses:
            for key, value in EXPECTED.items():
                assert response.headers[key] == value, (environment, key)
            has_hsts = "Strict-Transport-Security" in response.headers
            assert has_hsts == (environment != "local")
    assert client.post("/health").status_code == 405
    assert client.get("/health").headers["Strict-Transport-Security"] == (
        "max-age=31536000; includeSubDomains"
    )


def test_validation_error_422_carries_security_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    app = app_for("local", monkeypatch)

    @app.get("/needs-int")
    def needs_int(n: int) -> int:
        return n

    response = TestClient(app).get("/needs-int?n=x")
    assert response.status_code == 422
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Security-Policy"] == EXPECTED["Content-Security-Policy"]


def test_docs_endpoints_disabled_outside_local_and_relaxed_csp_only_in_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prod = TestClient(app_for("staging", monkeypatch))
    assert all(prod.get(p).status_code == 404 for p in ("/docs", "/redoc", "/openapi.json"))
    local = TestClient(app_for("local", monkeypatch))
    docs = local.get("/docs")
    assert docs.status_code == 200
    assert "cdn.jsdelivr.net" in docs.headers["Content-Security-Policy"]
    assert (
        local.get("/health").headers["Content-Security-Policy"]
        == EXPECTED["Content-Security-Policy"]
    )


def test_frontend_headers_file_has_strict_csp() -> None:
    text = (Path(__file__).parents[2] / "frontend/public/_headers").read_text()
    for part in (
        "default-src 'self'",
        "script-src 'self'",
        "connect-src 'self' __API_ORIGIN__",
        "frame-ancestors 'none'",
        "object-src 'none'",
        "X-Content-Type-Options: nosniff",
    ):
        assert part in text


def fmt(**extras: object) -> dict[str, object]:
    record = make_record()
    record.__dict__.update(extras)
    data: dict[str, object] = json.loads(render(record))
    return data


def test_f_string_style_event_from_our_logger_is_replaced_not_emitted() -> None:
    record = logging.LogRecord("app.x", logging.INFO, "f", 1, f"user {SECRET} synced", (), None)
    output = render(record)
    assert json.loads(output)["event"] == "invalid_event" and SECRET not in output


def test_third_party_events_are_emitted_as_thirdparty_with_logger_name_only() -> None:
    record = logging.LogRecord("httpx", logging.INFO, "f", 1, "HTTP Request: %s", (SECRET,), None)
    data = json.loads(render(record))
    assert data["event"] == "thirdparty" and data["logger"] == "httpx"
    assert SECRET not in json.dumps(data)


def test_allowed_fields_are_validated_and_invalid_ones_dropped() -> None:
    data = fmt(
        user_id="not-a-uuid",
        request_id=str(uuid.uuid4()),
        status="200",
        duration_ms=1.5,
        count=True,
        error_code=SECRET + " with spaces",
        mode="initial",
        method="GET",
        path="/a/b?token=" + SECRET + "#frag",
    )
    assert data["dropped_fields"] == ["count", "error_code", "status", "user_id"]
    assert data["path"] == "/a/b" and data["mode"] == "initial" and data["duration_ms"] == 1.5
    assert SECRET not in json.dumps(data)


def test_request_log_uses_route_template_or_unmatched(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    app = client.app
    assert isinstance(app, FastAPI)

    @app.get("/items/{item_id}")
    def item(item_id: str) -> str:
        return item_id

    client.get("/items/secret-123")
    client.get("/missing/secret-456")
    paths = [r.path for r in logged(caplog, "app.request")]  # type: ignore[attr-defined]
    assert paths[-2:] == ["/items/{item_id}", "unmatched"]


def test_unhandled_error_returns_json_500_with_headers_and_logs_exc_type_only(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    app = app_for("prod", monkeypatch)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError(SECRET)

    response = TestClient(app).get("/boom")
    assert response.status_code == 500 and response.json() == {"detail": "internal_error"}
    assert uuid.UUID(response.headers["X-Request-ID"])
    for key, value in EXPECTED.items():
        assert response.headers[key] == value
    assert "Strict-Transport-Security" in response.headers
    output = render(logged(caplog, "app.request")[-1])
    data = json.loads(output)
    assert data["status"] == 500 and data["exc_type"] == "RuntimeError"
    assert SECRET not in output and "Traceback" not in output


def test_head_health_is_allowed(client: TestClient) -> None:
    assert client.head("/health").status_code == 200


def check_deploy(tmp_path: Path, content: str, deploy: str | None) -> int:
    headers = tmp_path / "_headers"
    headers.write_text(content)
    env = {k: v for k, v in os.environ.items() if k != "DEPLOY"}
    if deploy:
        env["DEPLOY"] = deploy
    script = Path(__file__).parents[2] / "frontend/scripts/check-deploy-headers.mjs"
    return subprocess.run(["node", str(script), str(headers)], env=env, check=False).returncode  # noqa: S603, S607


def test_deploy_check_fails_only_with_deploy_set_and_placeholder_present(tmp_path: Path) -> None:
    assert check_deploy(tmp_path, "connect-src 'self' __API_ORIGIN__", "1") == 1
    assert check_deploy(tmp_path, "connect-src 'self' https://api.example.test", "1") == 0
    assert check_deploy(tmp_path, "connect-src 'self' __API_ORIGIN__", None) == 0
