"""Operator CLI: `python -m app.cli invite create [--email E] [--days N]`, `tokens rotate`,
`session create --email E` (local environment only)."""

import argparse
import re
import sys
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import User
from app.repositories import invite_codes, oauth_tokens, users
from app.security import sessions
from app.security.crypto import Keyring, KeyringError, get_keyring
from app.security.invite_codes import generate_code, hash_code

DEFAULT_DAYS = 14
MAX_DAYS = 90
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

SessionFactory = Callable[[], AbstractContextManager[Session]]
Clock = Callable[[], datetime]
KeyringFactory = Callable[[], Keyring]


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
    tokens = commands.add_parser("tokens").add_subparsers(dest="action", required=True)
    tokens.add_parser("rotate", help="re-encrypt refresh tokens under the current key")
    session = commands.add_parser("session").add_subparsers(dest="action", required=True)
    session_create = session.add_parser("create", help="local only: print a session cookie")
    session_create.add_argument("--email", type=_email, required=True)
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
    keyring_factory: KeyringFactory = get_keyring,
) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    if args.command == "session":
        return _create_dev_session(args.email, session_factory, clock)
    if args.command == "tokens":
        return _rotate_tokens(session_factory, keyring_factory)
    now = clock()
    with session_factory() as session:
        invite_codes.lock_user_cap(session)
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


def _create_dev_session(email: str, session_factory: SessionFactory, clock: Clock) -> int:
    settings = get_settings()
    if settings.environment != "local":
        print("error: session create only runs when ENVIRONMENT=local", file=sys.stderr)
        return 1
    with session_factory() as session:
        user = users.get_by_email(session, email)
        if user is None:
            user = User(google_sub=f"local:{email}", email=email)
            session.add(user)
            session.flush()
        raw, csrf, _ = sessions.create_session(session, user.id, clock(), settings)
        session.commit()
    print(f"{settings.session_cookie}={raw}")
    print(f"{settings.csrf_cookie}={csrf}")
    return 0


def _rotate_tokens(session_factory: SessionFactory, keyring_factory: KeyringFactory) -> int:
    try:
        keyring = keyring_factory()
    except KeyringError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ValueError:
        print("error: invalid token encryption configuration", file=sys.stderr)
        return 1
    with session_factory() as session:
        result = oauth_tokens.rotate_all(session, keyring)
        session.commit()
    print(f"rotated={result.rotated} failed={result.failed}")
    for user_id in result.failed_user_ids:
        print(f"failed user_id: {user_id}", file=sys.stderr)
    return 1 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main())
