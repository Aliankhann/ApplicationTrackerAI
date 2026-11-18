from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.api import applications, auth, followups, gmail, health, sequences, unsubscribe
from app.api import settings as settings_api
from app.api.deps import SignInRedirect, require_csrf
from app.config import get_settings
from app.log import configure_logging
from app.middleware import OriginCheckMiddleware, RequestLogMiddleware, SecurityHeadersMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)
    docs = (
        {}
        if settings.environment == "local"
        else {"docs_url": None, "redoc_url": None, "openapi_url": None}
    )
    app = FastAPI(
        title="Application Tracker API",
        version="0.1.0",
        dependencies=[Depends(require_csrf)],
        **docs,  # type: ignore[arg-type]
    )

    @app.exception_handler(SignInRedirect)
    def sign_in_redirect(_: Request, exc: SignInRedirect) -> RedirectResponse:
        query = urlencode({"error": exc.code})
        return RedirectResponse(f"{settings.frontend_origin}/sign-in?{query}", status_code=302)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )
    app.add_middleware(OriginCheckMiddleware, allowed_origin=settings.frontend_origin)
    app.add_middleware(RequestLogMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, environment=settings.environment)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(applications.router)
    app.include_router(followups.router)
    app.include_router(gmail.router)
    app.include_router(sequences.router)
    app.include_router(settings_api.router)
    app.include_router(unsubscribe.router)
    return app


app = create_app()
