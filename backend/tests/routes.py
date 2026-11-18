"""Route enumeration shared by the CSRF and isolation suites."""

import re
import uuid
from collections.abc import Iterator, Sequence
from typing import Any

from fastapi import FastAPI

from app.api.deps import PUBLIC_ROUTES
from app.main import app as real_app

STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}
PARAM = re.compile(r"\{([^}]+)\}")


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
        (method, PARAM.sub(lambda _: str(uuid.uuid4()), path))
        for method, path in walk(app.routes)
        if method in STATE_CHANGING and (method, path) not in PUBLIC_ROUTES
    )


def all_routes(app: FastAPI = real_app) -> list[tuple[str, str]]:
    """(METHOD, path template) for every route except HEAD, sorted."""
    return sorted((m, p) for m, p in walk(app.routes) if m not in {"HEAD", "OPTIONS"})
