"""Pure follow-up rules: send window, due times, daily cap, stop conditions. No DB, no I/O."""

import re
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from app.providers.gmail.types import MessageMeta, ThreadMeta
from app.services.classification import ApplicationStatus

DAILY_DRAFT_CAP = 5
WINDOW_START = time(9, 0)
WINDOW_END = time(11, 0)
_ADVANCED = frozenset(
    {ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER, ApplicationStatus.REJECTED}
)


class StopReason(StrEnum):
    """Stable cancel codes stored on follow_up_tasks.cancel_reason."""

    REPLY_RECEIVED = "reply_received"
    STATUS_ADVANCED = "status_advanced"
    PAUSED = "paused"
    MAX_ATTEMPTS = "max_attempts"
    USER_ALREADY_SENT = "user_already_sent"
    DRAFT_EDITED_OR_SENT = "draft_edited_or_sent"
    GMAIL_DISCONNECTED = "gmail_disconnected"
    THREAD_MISSING = "thread_missing"
    NO_REPLY_RECIPIENT = "no_reply_recipient"
    SELF_RECIPIENT = "self_recipient"
    GMAIL_ERROR = "gmail_error"
    UNCERTAIN_DRAFT = "uncertain_draft"
    STALE_ON_PLAN = "stale_on_plan"


class Decision(StrEnum):
    DRAFT = "draft"
    SKIP_WINDOW = "skip_window"
    SKIP_CAP = "skip_cap"


def local_to_utc(day: date, at: time, tz: ZoneInfo) -> datetime:
    """Local wall time to UTC. Ambiguous times use fold=0 (first occurrence); a time inside a
    spring-forward gap is read with the pre-change offset, so it lands after the gap."""
    return datetime.combine(day, at, tzinfo=tz).astimezone(UTC)


def in_send_window(now_utc: datetime, tz: ZoneInfo) -> bool:
    local = now_utc.astimezone(tz)
    return local.weekday() < 5 and WINDOW_START <= local.time() < WINDOW_END


def next_window_start(now_utc: datetime, tz: ZoneInfo) -> datetime:
    """`now_utc` when inside the window, else the next 09:00 local on a weekday (UTC)."""
    if in_send_window(now_utc, tz):
        return now_utc
    today = now_utc.astimezone(tz).date()
    for offset in range(8):
        day = today + timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        start = local_to_utc(day, WINDOW_START, tz)
        if start >= now_utc:
            return start
    raise AssertionError("unreachable: a weekday always occurs within 8 days")


def due_at_for(applied_at_utc: datetime, delay_days: int, tz: ZoneInfo) -> datetime:
    """09:00 local on the local calendar date `delay_days` after the applied date (UTC)."""
    day = applied_at_utc.astimezone(tz).date() + timedelta(days=delay_days)
    return local_to_utc(day, WINDOW_START, tz)


def local_day_bounds(now_utc: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """[start, end) in UTC of the user's local calendar day containing `now_utc`."""
    day = now_utc.astimezone(tz).date()
    return local_to_utc(day, time(0), tz), local_to_utc(day + timedelta(days=1), time(0), tz)


def decide(now_utc: datetime, tz: ZoneInfo, drafted_today: int, cap: int) -> Decision:
    if not in_send_window(now_utc, tz):
        return Decision.SKIP_WINDOW
    if drafted_today >= cap:
        return Decision.SKIP_CAP
    return Decision.DRAFT


def real_messages(thread: ThreadMeta) -> tuple[MessageMeta, ...]:
    """Messages without drafts, which never count as anyone having sent or replied."""
    return tuple(m for m in thread.messages if not m.is_draft)


def _reply_received(real: tuple[MessageMeta, ...]) -> bool:
    return bool(real) and not real[-1].from_user


def _user_sent_since(real: tuple[MessageMeta, ...], since: datetime) -> bool:
    return any(m.from_user and m.sent_at > since for m in real)


def should_stop(
    app_status: ApplicationStatus,
    thread: ThreadMeta,
    *,
    since: datetime,
    paused: bool,
    attempts: int,
    max_attempts: int,
    gmail_revoked: bool = False,
) -> StopReason | None:
    """First stop reason that applies, or None. `since` is when the task was planned (or when
    the user last sent one of our drafts): a newer user message means they followed up."""
    real = real_messages(thread)
    if gmail_revoked:
        return StopReason.GMAIL_DISCONNECTED
    if paused:
        return StopReason.PAUSED
    if app_status in _ADVANCED:
        return StopReason.STATUS_ADVANCED
    if _reply_received(real):
        return StopReason.REPLY_RECEIVED
    if _user_sent_since(real, since):
        return StopReason.USER_ALREADY_SENT
    if attempts >= max_attempts:
        return StopReason.MAX_ATTEMPTS
    return None


_NO_REPLY = re.compile(r"no[-_.]?reply|do[-_.]?not[-_.]?reply|notifications?|mailer-daemon|bounce")


def recipient_stop(recipient: str, user_email: str) -> StopReason | None:
    """Stop when the To address cannot or should not receive a follow-up. Never log `recipient`."""
    if recipient.strip().lower() == user_email.strip().lower():
        return StopReason.SELF_RECIPIENT
    local = recipient.rsplit("@", 1)[0].lower()
    if _NO_REPLY.search(local):
        return StopReason.NO_REPLY_RECIPIENT
    return None
