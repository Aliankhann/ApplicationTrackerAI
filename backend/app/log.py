"""Structured JSON logging with an allowlist of fields.

Only the keys in `BASE_KEYS` and the extras named in `ALLOWED_FIELDS` are emitted. Other extras
are dropped and only their names are listed under `dropped_fields`. Exception messages and
tracebacks are never emitted, only the class name as `exc_type`. Events from our loggers must be
short constants (else `invalid_event`); third-party records are emitted as `thirdparty`.
"""

import json
import logging
import re
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

from app.config import Settings

BASE_KEYS = ("ts", "level", "logger", "event")
ALLOWED_FIELDS = frozenset(
    {
        "request_id",
        "user_id",
        "method",
        "path",
        "status",
        "duration_ms",
        "mode",
        "threads_seen",
        "threads_kept",
        "threads_dropped",
        "applications_changed",
        "error_code",
        "count",
        "job",
        "sent",
        "failed",
        "skipped",
        "exc_type",
    }
)
MAX_STRING = 200
_STANDARD_ATTRS = frozenset(
    {*logging.LogRecord("", 0, "", 0, "", (), None).__dict__, "message", "asctime", "taskName"}
)


_EVENT = re.compile(r"^[a-z0-9_.]+$")
_CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_UUID_FIELDS = frozenset({"request_id", "user_id"})
_NUMBER_FIELDS = frozenset(
    {
        "status",
        "count",
        "sent",
        "failed",
        "skipped",
        "duration_ms",
        "threads_seen",
        "threads_kept",
        "threads_dropped",
        "applications_changed",
    }
)
_CODE_FIELDS = frozenset({"error_code", "job", "mode", "method", "exc_type"})
_REJECT = object()


def _is_ours(name: str) -> bool:
    return name == "app" or name.startswith("app.")


def _uuid(value: object) -> object:
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        return _REJECT


def _sanitize(key: str, value: object) -> object:
    """Return the value to log for an allowed field, or _REJECT when it is not acceptable."""
    if key in _UUID_FIELDS:
        return _uuid(value)
    if key in _NUMBER_FIELDS:
        ok = isinstance(value, int | float) and not isinstance(value, bool)
        return value if ok else _REJECT
    if key in _CODE_FIELDS:
        return value if isinstance(value, str) and _CODE.match(value) else _REJECT
    if key == "path":
        return str(value).split("?")[0].split("#")[0][:MAX_STRING]
    return _REJECT


def _event(record: logging.LogRecord) -> str:
    """Our events are short constants; third-party templates are never emitted."""
    if not _is_ours(record.name):
        return "thirdparty"
    msg = record.msg
    return msg if isinstance(msg, str) and _EVENT.match(msg) else "invalid_event"


class AllowlistJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": _event(record),
        }
        dropped: list[str] = []
        for key, value in record.__dict__.items():
            if key in _STANDARD_ATTRS:
                continue
            clean = _sanitize(key, value) if key in ALLOWED_FIELDS else _REJECT
            if clean is _REJECT:
                dropped.append(key)
            else:
                out[key] = clean
        if record.exc_info and record.exc_info[0] is not None:
            out["exc_type"] = record.exc_info[0].__name__
        if dropped:
            out["dropped_fields"] = sorted(dropped)
        return json.dumps(out, default=str)


def configure_logging(settings: Settings) -> None:
    """Send all logs, including uvicorn's and SQLAlchemy's, through the allowlist formatter."""
    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, "_app_handler", False)]:
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(AllowlistJsonFormatter())
    handler._app_handler = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())
    for name in ("uvicorn", "uvicorn.error"):
        third = logging.getLogger(name)
        third.handlers.clear()
        third.propagate = True
        third.disabled = False
    access = logging.getLogger("uvicorn.access")  # replaced by the request log middleware
    access.handlers.clear()
    access.propagate = False
    access.disabled = True
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def parse_request_id(value: str | None) -> str:
    """Return the inbound id when it is a valid uuid, else a fresh uuid4."""
    if value:
        try:
            return str(uuid.UUID(value))
        except ValueError:
            pass
    return str(uuid.uuid4())
