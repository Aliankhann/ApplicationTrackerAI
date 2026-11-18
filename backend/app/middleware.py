"""Pure ASGI middleware: request logging and security headers."""

import logging
import time
from typing import Any

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.log import get_logger, parse_request_id

logger = get_logger("app.request")

CSP_STRICT = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
# Swagger UI and ReDoc load assets from a CDN and use inline scripts; local environment only.
CSP_DOCS = (
    "default-src 'none'; script-src 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src data: https://fastapi.tiangolo.com; "
    "connect-src 'self'; worker-src blob:; frame-ancestors 'none'; base-uri 'none'"
)
DOCS_PATHS = frozenset({"/docs", "/redoc", "/openapi.json"})
HSTS = "max-age=31536000; includeSubDomains"
STATIC_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-site",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cache-Control": "no-store",
}


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, environment: str) -> None:
        self.app = app
        self.environment = environment

    def _headers(self, path: str) -> dict[str, str]:
        local = self.environment == "local"
        headers = dict(STATIC_HEADERS)
        headers["Content-Security-Policy"] = (
            CSP_DOCS if local and path in DOCS_PATHS else CSP_STRICT
        )
        if not local:
            headers["Strict-Transport-Security"] = HSTS
        return headers

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        extra = self._headers(scope["path"])

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for key, value in extra.items():
                    headers[key] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)


class RequestLogMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = parse_request_id(Headers(scope=scope).get("x-request-id"))
        started = time.perf_counter()
        status = 500
        started_response = False

        async def send_with_id(message: Message) -> None:
            nonlocal status, started_response
            if message["type"] == "http.response.start":
                started_response = True
                status = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        fields: dict[str, Any] = {"request_id": request_id, "method": scope["method"]}
        try:
            await self.app(scope, receive, send_with_id)
        except Exception as exc:
            fields["exc_type"] = type(exc).__name__
            if started_response:
                self._log(scope, fields, started, 500)
                raise
            status = 500
            await JSONResponse({"detail": "internal_error"}, status_code=500)(
                scope, receive, send_with_id
            )
        self._log(scope, fields, started, status)

    @staticmethod
    def _log(scope: Scope, fields: dict[str, Any], started: float, status: int) -> None:
        route = scope.get("route")
        fields["path"] = getattr(route, "path", None) or "unmatched"
        fields["status"] = status
        fields["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
        logger.log(logging.ERROR if status >= 500 else logging.INFO, "http.request", extra=fields)


STATE_CHANGING = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class OriginCheckMiddleware:
    """Defense in depth: reject state-changing requests from a foreign Origin."""

    def __init__(self, app: ASGIApp, allowed_origin: str) -> None:
        self.app = app
        self.allowed_origin = allowed_origin

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in STATE_CHANGING:
            origin = Headers(scope=scope).get("origin")
            if origin is not None and origin != self.allowed_origin:
                await JSONResponse({"detail": "origin_rejected"}, status_code=403)(
                    scope, receive, send
                )
                return
        await self.app(scope, receive, send)
