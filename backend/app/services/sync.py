"""Gmail sync: initial 90-day pull and incremental sync from history.

Only job threads are written; everything else is dropped before any write. Nothing here logs
or stores exception messages, subjects, or snippets.

Transactions: work is committed per batch through the `commit` callable (default
`session.commit`), so a crash keeps completed batches and reprocessing is idempotent. Because
commits end transactions, the per-user lock is a session-level advisory lock released in
`finally` rather than a transaction-level one (which the first commit would drop).
"""

import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Literal, TypeVar

from sqlalchemy import or_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.log import get_logger
from app.models import EmailThread, SyncState, SyncStatus
from app.providers.classifier.base import ClassifierProvider, UserBoundClassifier
from app.providers.classifier.types import ClassificationInput, ClassificationResult
from app.providers.gmail import (
    GmailAuthRevoked,
    GmailClient,
    GmailError,
    GmailHistoryExpired,
    GmailNotFound,
    GmailRateLimited,
    MessageMeta,
    ThreadMeta,
)
from app.repositories import applications as applications_repo
from app.repositories import oauth_tokens as tokens_repo
from app.repositories import threads as threads_repo
from app.services.applications import record_classification
from app.services.extraction import SOURCE_LLM, Extracted, extract
from app.services.prefilter import EmailMeta, prefilter, sender_domain

INITIAL_QUERY = "newer_than:90d"
BATCH_SIZE = 50
MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 1.0
MAX_SNIPPET = 200
MAX_RETRY_AFTER = 60.0
PIPELINE_VERSION = "1"  # bump when prefilter, classifier, or extraction change

ERROR_AUTH_REVOKED = "auth_revoked"
ERROR_RATE_LIMITED = "rate_limited"
ERROR_GMAIL = "gmail_error"
ERROR_INTERNAL = "internal_error"

logger = get_logger("app.sync")
Mode = Literal["initial", "incremental", "fallback_full"]
T = TypeVar("T")


@dataclass(frozen=True)
class SyncResult:
    threads_seen: int
    threads_kept: int
    threads_dropped: int
    applications_changed: int
    mode: Mode
    history_id: str


@dataclass(frozen=True)
class SyncAlreadyRunning:
    """Returned when another sync holds the user's lock; no work was done."""


@dataclass(frozen=True)
class SyncUserGone:
    """The user was deleted mid-sync; the run stopped and wrote nothing further."""


class SyncRevoked(Exception):
    """The user's Google grant is gone; the token and sync state are flagged revoked."""


class _UserGone(Exception):
    """Internal: the user row vanished while syncing."""


class SyncFailed(Exception):
    """Sync stopped on a Gmail error; `code` is the stable code stored in sync_state."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class _Counts:
    seen: int = 0
    kept: int = 0
    changed: int = 0

    @property
    def dropped(self) -> int:
        return self.seen - self.kept


class _Context:
    def __init__(
        self,
        session: Session,
        user_id: uuid.UUID,
        client: GmailClient,
        classifier: ClassifierProvider,
        now: datetime,
        commit: Callable[[], None],
        sleep: Callable[[float], None],
        clock: Callable[[], datetime],
        force: bool,
    ) -> None:
        self.session = session
        self.user_id = user_id
        self.client = client
        self.classifier = classifier
        self.now = now
        self.commit = commit
        self.sleep = sleep
        self.clock = clock
        self.force = force
        self.state: SyncState

    def call(self, fn: Callable[[], T]) -> T:
        """Run a Gmail call, retrying rate limits with exponential backoff."""
        for attempt in range(MAX_ATTEMPTS):
            try:
                return fn()
            except GmailRateLimited as exc:
                if attempt == MAX_ATTEMPTS - 1:
                    raise
                self.sleep(
                    min(exc.retry_after or BACKOFF_BASE_SECONDS * 2**attempt, MAX_RETRY_AFTER)
                )
        raise AssertionError("unreachable")


def _lease() -> timedelta:
    return timedelta(minutes=get_settings().sync_lease_minutes)


def _claim(ctx: _Context) -> SyncState | None:
    """Atomically take the user's lease; None when a live sync already holds it."""
    try:
        ctx.session.execute(
            insert(SyncState)
            .values(user_id=ctx.user_id)
            .on_conflict_do_nothing(index_elements=["user_id"])
        )
    except IntegrityError:  # no such user (deleted): the foreign key refuses the lease row
        ctx.session.rollback()
        raise _UserGone from None
    stmt = (
        update(SyncState)
        .where(
            SyncState.user_id == ctx.user_id,
            or_(SyncState.status != SyncStatus.RUNNING.value, SyncState.lease_expires_at < ctx.now),
        )
        .values(
            status=SyncStatus.RUNNING.value,
            started_at=ctx.now,
            lease_expires_at=ctx.now + _lease(),
            last_error=None,
        )
        .execution_options(synchronize_session=False)
    )
    claimed = ctx.session.execute(stmt).rowcount == 1  # type: ignore[attr-defined]
    ctx.commit()
    if not claimed:
        return None
    return ctx.session.get(SyncState, ctx.user_id, populate_existing=True)


def _checkpoint(ctx: _Context) -> None:
    """Commit the batch and extend the lease."""
    ctx.state.lease_expires_at = ctx.clock() + _lease()
    ctx.session.flush()
    ctx.commit()


def _batches(items: list[str]) -> Iterator[list[str]]:
    for i in range(0, len(items), BATCH_SIZE):
        yield items[i : i + BATCH_SIZE]


def _chosen_message(meta: ThreadMeta) -> MessageMeta | None:
    """Latest non-draft message from someone else; else the first non-draft; None if drafts only."""
    real = [m for m in meta.messages if not m.is_draft]
    if not real:
        return None
    others = [m for m in real if not m.from_user]
    return others[-1] if others else real[0]


def _process_thread(ctx: _Context, meta: ThreadMeta, counts: _Counts) -> None:
    counts.seen += 1
    message = _chosen_message(meta)
    if message is None:
        return
    snippet = message.snippet[:MAX_SNIPPET]
    email = EmailMeta(message.from_address, message.from_name, message.subject, snippet)
    if not prefilter(email).keep:
        return
    counts.kept += 1
    existing = threads_repo.get_by_gmail_id(ctx.session, ctx.user_id, meta.thread_id)
    if (
        existing is not None
        and not ctx.force
        and threads_repo.is_unchanged(existing, meta, PIPELINE_VERSION)
    ):
        return
    domain = sender_domain(message.from_address)
    thread = threads_repo.upsert_thread(
        ctx.session, ctx.user_id, meta, message.subject, domain, snippet, PIPELINE_VERSION
    )
    result = ctx.classifier.classify(ClassificationInput(domain, message.subject, snippet))
    extracted = _with_llm_fields(
        extract(message.from_address, message.from_name, message.subject, snippet), result
    )
    if _record(ctx, thread, result, extracted):
        counts.changed += 1


def _with_llm_fields(extracted: Extracted, result: ClassificationResult) -> Extracted:
    """Rules extraction wins; the (already cleaned) LLM suggestion only fills gaps."""
    if result.method != "llm":
        return extracted
    return replace(
        extracted,
        company=extracted.company or result.company,
        role=extracted.role or result.role,
        company_source=extracted.company_source or (SOURCE_LLM if result.company else None),
        role_source=extracted.role_source or (SOURCE_LLM if result.role else None),
    )


def _record(
    ctx: _Context, thread: EmailThread, result: ClassificationResult, extracted: Extracted
) -> bool:
    before = applications_repo.get_for_thread(ctx.session, ctx.user_id, thread.id)
    before_status = before.status if before else None
    application = record_classification(
        ctx.session, ctx.user_id, thread, result, extracted, ctx.now
    )
    return application is not None and application.status != before_status


def _fetch(ctx: _Context, ids: list[str]) -> list[ThreadMeta]:
    """Batch fetch; if a thread vanished (deleted), fetch the rest one by one."""
    try:
        return ctx.call(lambda: ctx.client.get_threads(ids))
    except GmailNotFound:
        found: list[ThreadMeta] = []
        for thread_id in ids:
            try:
                found.append(ctx.call(partial(ctx.client.get_thread, thread_id)))
            except GmailNotFound:
                continue
        return found


def _process_ids(ctx: _Context, ids: list[str]) -> _Counts:
    counts = _Counts()
    for batch in _batches(ids):
        for meta in _fetch(ctx, batch):
            _process_thread(ctx, meta, counts)
        _checkpoint(ctx)
    return counts


def _list_all_thread_ids(ctx: _Context) -> list[str]:
    ids: dict[str, None] = {}
    token: str | None = None
    while True:
        page, token = ctx.call(partial(ctx.client.list_threads, INITIAL_QUERY, token))
        ids.update(dict.fromkeys(s.thread_id for s in page))
        if token is None:
            return list(ids)


def _list_changed_thread_ids(ctx: _Context, start: str) -> tuple[list[str], str]:
    ids: dict[str, None] = {}
    token: str | None = None
    while True:
        page = ctx.call(partial(ctx.client.list_history, start, token))
        ids.update(dict.fromkeys(page.changed_thread_ids))
        if page.next_page_token is None:
            return list(ids), page.history_id
        token = page.next_page_token


def _newest(stored: str | None, new: str) -> str:
    """Never move the history id backwards (ids compare as integers)."""
    return new if stored is None or int(new) >= int(stored) else stored


def _release(state: SyncState, status: SyncStatus, error: str | None) -> None:
    state.status = status.value
    state.last_error = error
    state.lease_expires_at = None


def _finish(
    ctx: _Context, state: SyncState, history_id: str, counts: _Counts, mode: Mode
) -> SyncResult:
    state.history_id = _newest(state.history_id, history_id)
    state.initial_sync_done = True
    state.last_synced_at = ctx.now
    _release(state, SyncStatus.IDLE, None)
    ctx.session.flush()
    ctx.commit()
    return SyncResult(
        counts.seen, counts.kept, counts.dropped, counts.changed, mode, state.history_id
    )


def _initial(ctx: _Context, state: SyncState, mode: Mode) -> SyncResult:
    # Taken before listing so changes made during the sync are picked up next time.
    history_id = ctx.call(ctx.client.get_profile).history_id
    counts = _process_ids(ctx, _list_all_thread_ids(ctx))
    return _finish(ctx, state, history_id, counts, mode)


def _incremental(ctx: _Context, state: SyncState, start: str) -> SyncResult:
    ids, history_id = _list_changed_thread_ids(ctx, start)
    counts = _process_ids(ctx, ids)
    return _finish(ctx, state, history_id, counts, "incremental")


def _dispatch(ctx: _Context, state: SyncState) -> SyncResult:
    if not state.initial_sync_done or state.history_id is None:
        return _initial(ctx, state, "initial")
    try:
        return _incremental(ctx, state, state.history_id)
    except GmailHistoryExpired:
        ctx.force = True
        return _initial(ctx, state, "fallback_full")


def _record_failure(ctx: _Context, status: SyncStatus, code: str) -> None:
    _release(ctx.state, status, code)
    ctx.session.flush()
    ctx.commit()


def _log_failed(ctx: _Context, code: str) -> None:
    logger.warning("sync.failed", extra={"user_id": ctx.user_id, "error_code": code})


def _log_completed(ctx: _Context, result: SyncResult) -> None:
    logger.info(
        "sync.completed",
        extra={
            "user_id": ctx.user_id,
            "mode": result.mode,
            "threads_seen": result.threads_seen,
            "threads_kept": result.threads_kept,
            "threads_dropped": result.threads_dropped,
            "applications_changed": result.applications_changed,
        },
    )


def _run_claimed(ctx: _Context) -> SyncResult | SyncUserGone:
    try:
        result = _dispatch(ctx, ctx.state)
        _log_completed(ctx, result)
        return result
    except GmailAuthRevoked:
        tokens_repo.mark_revoked(ctx.session, ctx.user_id)
        _record_failure(ctx, SyncStatus.REVOKED, ERROR_AUTH_REVOKED)
        _log_failed(ctx, ERROR_AUTH_REVOKED)
        raise SyncRevoked from None
    except GmailRateLimited:
        _record_failure(ctx, SyncStatus.ERROR, ERROR_RATE_LIMITED)
        _log_failed(ctx, ERROR_RATE_LIMITED)
        raise SyncFailed(ERROR_RATE_LIMITED) from None
    except GmailError:
        _record_failure(ctx, SyncStatus.ERROR, ERROR_GMAIL)
        _log_failed(ctx, ERROR_GMAIL)
        raise SyncFailed(ERROR_GMAIL) from None
    except Exception:
        ctx.session.rollback()
        state = ctx.session.get(SyncState, ctx.user_id, populate_existing=True)
        if state is None:  # the account was deleted under us: stop, recreate nothing
            logger.info("sync.user_gone", extra={"user_id": ctx.user_id})
            return SyncUserGone()
        ctx.state = state
        _record_failure(ctx, SyncStatus.ERROR, ERROR_INTERNAL)
        _log_failed(ctx, ERROR_INTERNAL)
        raise


def _utcnow() -> datetime:
    return datetime.now(UTC)


def run_sync(
    session: Session,
    user_id: uuid.UUID,
    client: GmailClient,
    classifier: ClassifierProvider,
    now: datetime,
    *,
    commit: Callable[[], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], datetime] | None = None,
    force: bool = False,
) -> SyncResult | SyncAlreadyRunning | SyncUserGone:
    """Sync one user. Raises SyncRevoked or SyncFailed after recording the state.

    One sync per user: a lease row in sync_state is claimed atomically at `now` and extended
    after each committed batch using `clock` (default: the real UTC clock, so long syncs keep
    their lease; tests pass a fake clock). `force` reprocesses threads even when unchanged.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if isinstance(classifier, UserBoundClassifier):
        classifier = classifier.for_user(session, user_id)
    ctx = _Context(
        session,
        user_id,
        client,
        classifier,
        now,
        commit or session.commit,
        sleep,
        clock or _utcnow,
        force,
    )
    try:
        state = _claim(ctx)
    except _UserGone:
        return SyncUserGone()
    if state is None:
        return SyncAlreadyRunning()
    ctx.state = state
    return _run_claimed(ctx)
