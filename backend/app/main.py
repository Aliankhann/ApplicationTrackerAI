from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, health
from app.api.deps import require_csrf
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
    return app


app = create_app()
