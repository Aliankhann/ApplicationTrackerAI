"""Daily digest job: one email per enabled user per local day, never two.

Safety order for each user: claim the digest_log row (committed) BEFORE sending, so a crash or a
concurrent run can only ever lose a digest, not duplicate it.
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import quote

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.log import get_logger
from app.models import User
from app.providers.email import (
    EmailSender,
    EmailSendError,
    OutgoingEmail,
    sender_for,
)
from app.repositories import digest as repo
from app.security.unsubscribe import create_token
from app.services.digest import Digest, build_digest, render_html, render_text
from app.services.scheduler import user_timezone

logger = get_logger("app.digest")
FIRST_DIGEST_LOOKBACK = timedelta(hours=24)
ERROR_UNEXPECTED = "unexpected"


def unsubscribe_url(settings: Settings, user_id: uuid.UUID, now: datetime) -> str:
    token = create_token(settings.session_secret.get_secret_value(), user_id, now)
    return f"{settings.api_base_url.rstrip('/')}/unsubscribe?token={quote(token)}"


def compose(settings: Settings, user: User, digest: Digest, now: datetime) -> OutgoingEmail:
    url = unsubscribe_url(settings, user.id, now)
    return OutgoingEmail(
        to_address=user.email,
        subject=digest.subject,
        text=render_text(digest, url),
        html=render_html(digest, url),
        headers={
            "List-Unsubscribe": f"<{url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
    )


def _claim(session: Session, user_id: uuid.UUID, day: date, now: datetime) -> bool:
    """True when this run owns today's attempt: first claim, or the single retry of a failure.

    A user deleted since the user list was read violates the foreign key; that is a quiet skip.
    """
    try:
        with session.begin_nested():
            repo.fail_stale(session, user_id, day, now)
            return repo.claim(session, user_id, day, now) or repo.reclaim_failed(
                session, user_id, day, now
            )
    except IntegrityError:
        return False


def _attempt(
    session: Session, sender: EmailSender, settings: Settings, user: User, day: date, now: datetime
) -> str:
    """Build and send after the claim is committed; returns the final status."""
    if not repo.still_enabled(session, user.id):  # turned off or disabled since the list was read
        return repo.SKIPPED_EMPTY
    since = repo.last_sent_at(session, user.id) or now - FIRST_DIGEST_LOOKBACK
    digest = build_digest(session, user.id, since, now, user_timezone(user))
    if digest is None:
        return repo.SKIPPED_EMPTY
    sender.send(compose(settings, user, digest, now))
    return repo.SENT


def _run_user(
    session: Session, sender: EmailSender, settings: Settings, user: User, now: datetime
) -> str | None:
    user_id = user.id
    local = now.astimezone(user_timezone(user))
    if local.time() < time(settings.digest_hour):
        return None
    day = local.date()
    claimed = _claim(session, user_id, day, now)
    session.commit()
    if not claimed:
        return None
    try:
        status = _attempt(session, sender, settings, user, day, now)
    except Exception as exc:
        session.rollback()
        code = exc.code if isinstance(exc, EmailSendError) else ERROR_UNEXPECTED
        logger.warning("digest.failed", extra={"user_id": user_id, "error_code": code})
        status = repo.FAILED
    repo.finish(session, user_id, day, status, now if status == repo.SENT else None)
    session.commit()
    return status


def _run_user_isolated(
    session: Session, sender: EmailSender, settings: Settings, user: User, now: datetime
) -> str | None:
    """One user's failure (even outside the send) never aborts the others."""
    user_id = user.id
    try:
        return _run_user(session, sender, settings, user, now)
    except Exception as exc:
        session.rollback()
        logger.error(
            "digest.user_error", extra={"user_id": user_id, "exc_type": type(exc).__name__}
        )
        return repo.FAILED


def run_digest(
    session: Session, sender: EmailSender, now: datetime, settings: Settings | None = None
) -> dict[str, int]:
    """Send today's digest to every enabled user past the digest hour. Returns counts by status."""
    settings = settings or get_settings()
    counts = {repo.SENT: 0, repo.FAILED: 0, repo.SKIPPED_EMPTY: 0}
    for user in repo.enabled_users(session):
        status = _run_user_isolated(session, sender, settings, user, now)
        if status is not None:
            counts[status] += 1
    logger.info(
        "digest.run",
        extra={
            "job": "digest",
            "sent": counts[repo.SENT],
            "failed": counts[repo.FAILED],
            "skipped": counts[repo.SKIPPED_EMPTY],
        },
    )
    return counts


def main() -> None:
    from app.db import SessionLocal

    settings = get_settings()
    with SessionLocal() as session:
        run_digest(session, sender_for(settings.environment), datetime.now(UTC), settings)


if __name__ == "__main__":
    main()
