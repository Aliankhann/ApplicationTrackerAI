"""Operator CLI: `python -m app.cli invite create [--email E] [--days N]`."""

import argparse
import re
import sys
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.config import get_settings
from app.repositories import invite_codes
from app.security.invite_codes import generate_code, hash_code

DEFAULT_DAYS = 14
MAX_DAYS = 90
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

SessionFactory = Callable[[], AbstractContextManager[Session]]
Clock = Callable[[], datetime]


def _days(value: str) -> int:
    try:
        days = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if not 1 <= days <= MAX_DAYS:
        raise argparse.ArgumentTypeError(f"must be between 1 and {MAX_DAYS}")
    return days


def _email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 320 or not EMAIL_RE.match(email):
        raise argparse.ArgumentTypeError("invalid email address")
    return email


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    invite = commands.add_parser("invite").add_subparsers(dest="action", required=True)
    create = invite.add_parser("create", help="create a single-use invite code")
    create.add_argument("--email", type=_email, default=None)
    create.add_argument("--days", type=_days, default=DEFAULT_DAYS)
    return parser


def _default_session_factory() -> AbstractContextManager[Session]:
    from app.db import SessionLocal

    return SessionLocal()


def _utcnow() -> datetime:
    return datetime.now(UTC)


def main(
    argv: Sequence[str] | None = None,
    session_factory: SessionFactory = _default_session_factory,
    clock: Clock = _utcnow,
) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    now = clock()
    with session_factory() as session:
        if invite_codes.slots_in_use(session, now) >= get_settings().max_users:
            print("error: user cap reached; no invite created", file=sys.stderr)
            return 1
        code = generate_code()
        expires_at = now + timedelta(days=args.days)
        invite_codes.create(session, hash_code(code), expires_at, args.email)
        session.commit()
    print(f"Invite code: {code}")
    print(f"Expires: {expires_at.isoformat()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
