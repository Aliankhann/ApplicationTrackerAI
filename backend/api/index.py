"""Vercel entry point: the Python runtime serves the ASGI `app` exposed by this module.

Assumption (verify on first deploy): Vercel's Python runtime detects an ASGI `app` in `api/*.py`,
and `backend/vercel.json` rewrites every path here, so FastAPI sees the original request path.
"""

from app.main import app

__all__ = ["app"]
