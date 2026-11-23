"""Gmail sync: initial pull (last `initial_sync_days`, default 30) and incremental from history.

Only job threads are written; everything else is dropped before any write. Nothing here logs
or stores exception messages, subjects, or snippets.

Transactions: work is committed per batch through the `commit` callable (default
`session.commit`), so a crash keeps completed batches and reprocessing is idempotent. The per-user
lock is a lease row in sync_state (no session-level database state, so it works behind a
transaction-mode pooler).

Time budget: given a `deadline`, a run stops between batches once it has passed (after at least one
batch, so every run makes progress), commits, releases the lease, and returns SyncPartial. The
initial sync stores its history id and Gmail list page token, so the next run continues from that
page instead of relisting; history_id is only stored when the initial sync completes.
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
    GmailRateLimited,
    MessageMeta,
    ThreadMeta,
    ThreadSummary,
)
from app.repositories import applications as applications_repo
from app.repositories import oauth_tokens as tokens_repo
from app.repositories import threads as threads_repo
from app.services.applications import record_classification
from app.services.extraction import SOURCE_LLM, Extracted, extract
from app.services.prefilter import EmailMeta, prefilter, sender_domain

MAX_CONSECUTIVE_RATE_LIMITS = 3  # rate-limited runs in a row before the sync is shown as an error
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
class SyncPartial:
    """Stopped at the deadline; progress is committed and the next run continues."""

    threads_seen: int
    mode: Mode


@dataclass(frozen=True)
class SyncPaused:
    """Gmail kept rate limiting; progress is committed, the lease is free, the next run goes on."""

    threads_seen: int
    mode: Mode


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
        deadline: datetime | None,
        ensure_progress: bool = True,
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
        self.deadline = deadline
        self.ensure_progress = ensure_progress
        self.counts = _Counts()
        self.batches_done = 0
        self.rate_limit_hits = 0
        self.mode: Mode = "incremental"
        self.state: SyncState

    def out_of_time(self) -> bool:
        """Past the deadline. With `ensure_progress` (the cron path) never before this run has
        completed one batch, so every run advances; a manual run may stop right away."""
        if self.deadline is None or (self.ensure_progress and self.batches_done == 0):
            return False
        return self.clock() >= self.deadline

    def backoff(self, seconds: float) -> None:
        """Sleep for a rate-limit backoff, never past the deadline."""
        if self.deadline is not None:
            seconds = min(seconds, max((self.deadline - self.clock()).total_seconds(), 0.0))
        self.sleep(seconds)

    def time_left(self) -> float | None:
        """Seconds until the deadline (None: no deadline); bounds the client's retry sleeps."""
        if self.deadline is None:
            return None
        return max((self.deadline - self.clock()).total_seconds(), 0.0)

    def total_rate_limit_hits(self) -> int:
        return self.rate_limit_hits + self.client.rate_limit_hits

    def call(self, fn: Callable[[], T]) -> T:
        """Run one single-request Gmail call, retrying rate limits with exponential backoff.
        (Batch fetches retry per thread inside the client, so they are not wrapped here.)"""
        for attempt in range(MAX_ATTEMPTS):
            try:
                return fn()
            except GmailRateLimited as exc:
                self.rate_limit_hits += 1
                if attempt == MAX_ATTEMPTS - 1:
                    raise
                self.backoff(
                    min(exc.retry_after or BACKOFF_BASE_SECONDS * 2**attempt, MAX_RETRY_AFTER)
                )
        raise AssertionError("unreachable")


def _initial_query() -> str:
    return f"newer_than:{get_settings().initial_sync_days}d"


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


def _fetched_prefix(batch: list[str], metas: list[ThreadMeta]) -> int:
    """How many leading ids of the batch were fetched: safe to skip on a resume."""
    got = {meta.thread_id for meta in metas}
    count = 0
    for thread_id in batch:
        if thread_id not in got:
            break
        count += 1
    return count


def _process_ids(ctx: _Context, ids: list[str], *, resume_at: int | None = None) -> bool:
    """Process in committed batches; False when the deadline stopped it before the end. When
    Gmail stays rate limited, the threads that were fetched are kept, then it is re-raised.

    `resume_at` is for a list page of the initial sync: it starts at that offset and stores how
    far it got in `list_page_offset`, so a resumed run skips ids already fetched. (Ids that
    move because mail arrived meanwhile are covered by the incremental sync that follows.)"""
    track = resume_at is not None
    for start in range(resume_at or 0, len(ids), BATCH_SIZE):
        if ctx.out_of_time():
            return False
        batch = ids[start : start + BATCH_SIZE]
        limited: GmailRateLimited | None = None
        try:
            metas = ctx.client.get_threads(batch, ctx.time_left)
        except GmailRateLimited as exc:
            metas, limited = list(exc.fetched), exc
        for meta in metas:
            if ctx.out_of_time():  # budget ran out inside the batch: keep what is done
                _checkpoint(ctx)
                return False
            _process_thread(ctx, meta, ctx.counts)
        if track:
            done = len(batch) if limited is None else _fetched_prefix(batch, metas)
            ctx.state.list_page_offset = start + done
        _checkpoint(ctx)
        if limited is not None:
            raise limited
        ctx.batches_done += 1
    return True


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


def _pause(ctx: _Context, state: SyncState, mode: Mode) -> SyncPartial:
    """Out of time: keep the committed progress (and resume point), free the lease."""
    state.consecutive_rate_limits = 0
    _release(state, SyncStatus.IDLE, None)
    ctx.session.flush()
    ctx.commit()
    return SyncPartial(ctx.counts.seen, mode)


def _pause_rate_limited(ctx: _Context, state: SyncState) -> SyncPaused:
    """Gmail kept refusing: keep the progress, free the lease, and show "paused" (not an error)."""
    state.consecutive_rate_limits += 1
    _release(state, SyncStatus.PAUSED, ERROR_RATE_LIMITED)
    ctx.session.flush()
    ctx.commit()
    return SyncPaused(ctx.counts.seen, ctx.mode)


def _finish(ctx: _Context, state: SyncState, history_id: str, mode: Mode) -> SyncResult:
    counts = ctx.counts
    state.history_id = _newest(state.history_id, history_id)
    state.initial_sync_done = True
    state.pending_history_id = None
    state.list_page_token = None
    state.list_page_offset = 0
    state.last_synced_at = ctx.now
    state.consecutive_rate_limits = 0
    _release(state, SyncStatus.IDLE, None)
    ctx.session.flush()
    ctx.commit()
    return SyncResult(
        counts.seen, counts.kept, counts.dropped, counts.changed, mode, state.history_id
    )


def _start_listing(ctx: _Context, state: SyncState) -> None:
    # Taken before listing so changes made during the sync are picked up next time.
    state.pending_history_id = ctx.call(ctx.client.get_profile).history_id
    state.list_page_token = None  # committed with the first batch (or by _pause)
    state.list_page_offset = 0


def _list_page(
    ctx: _Context, state: SyncState, restarted: bool
) -> tuple[list[ThreadSummary], str | None, bool]:
    """One page of the initial listing. A stored page token Gmail rejects (it expired) would wedge
    the sync forever, so it is dropped and the listing restarts once from the first page."""
    token = state.list_page_token
    try:
        page, next_token = ctx.call(partial(ctx.client.list_threads, _initial_query(), token))
    except (GmailAuthRevoked, GmailRateLimited):
        raise
    except GmailError:
        if token is None or restarted:
            raise
        _start_listing(ctx, state)
        return _list_page(ctx, state, True)
    return page, next_token, restarted


def _pending(state: SyncState) -> str:
    if state.pending_history_id is None:
        raise ValueError("initial sync without a pending history id")
    return state.pending_history_id


def _initial(ctx: _Context, state: SyncState, mode: Mode) -> SyncResult | SyncPartial:
    if state.pending_history_id is None:
        _start_listing(ctx, state)
    restarted = False
    while True:
        page, next_token, restarted = _list_page(ctx, state, restarted)
        ids = list(dict.fromkeys(s.thread_id for s in page))
        if not _process_ids(ctx, ids, resume_at=state.list_page_offset):  # resumes mid-page
            return _pause(ctx, state, mode)
        if next_token is None:
            return _finish(ctx, state, _pending(state), mode)
        state.list_page_token = next_token
        state.list_page_offset = 0


def _incremental(ctx: _Context, state: SyncState, start: str) -> SyncResult | SyncPartial:
    ids, history_id = _list_changed_thread_ids(ctx, start)
    if not _process_ids(ctx, ids):  # history_id stays; unchanged threads are skipped next run
        return _pause(ctx, state, "incremental")
    return _finish(ctx, state, history_id, "incremental")


def _dispatch(ctx: _Context, state: SyncState) -> SyncResult | SyncPartial:
    if not state.initial_sync_done or state.history_id is None:
        ctx.mode = "initial"
        return _initial(ctx, state, "initial")
    try:
        return _incremental(ctx, state, state.history_id)
    except GmailHistoryExpired:
        ctx.force = True
        ctx.mode = "fallback_full"
        return _initial(ctx, state, "fallback_full")


def _record_failure(ctx: _Context, status: SyncStatus, code: str) -> None:
    _release(ctx.state, status, code)
    ctx.session.flush()
    ctx.commit()


def _log_failed(ctx: _Context, code: str) -> None:
    logger.warning(
        "sync.failed",
        extra={
            "user_id": ctx.user_id,
            "error_code": code,
            "rate_limit_hits": ctx.total_rate_limit_hits(),
        },
    )


def _log_completed(ctx: _Context, result: SyncResult | SyncPartial | SyncPaused) -> None:
    hits = ctx.total_rate_limit_hits()
    if isinstance(result, SyncPartial | SyncPaused):
        event = "sync.partial" if isinstance(result, SyncPartial) else "sync.paused"
        logger.info(
            event,
            extra={
                "user_id": ctx.user_id,
                "mode": result.mode,
                "threads_seen": result.threads_seen,
                "rate_limit_hits": hits,
            },
        )
        return
    logger.info(
        "sync.completed",
        extra={
            "user_id": ctx.user_id,
            "mode": result.mode,
            "threads_seen": result.threads_seen,
            "threads_kept": result.threads_kept,
            "threads_dropped": result.threads_dropped,
            "applications_changed": result.applications_changed,
            "rate_limit_hits": hits,
        },
    )


def _run_claimed(ctx: _Context) -> SyncResult | SyncPartial | SyncPaused | SyncUserGone:
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
        if ctx.state.consecutive_rate_limits + 1 < MAX_CONSECUTIVE_RATE_LIMITS:
            paused = _pause_rate_limited(ctx, ctx.state)
            _log_completed(ctx, paused)
            return paused
        ctx.state.consecutive_rate_limits = 0  # so a later throttle pauses again
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
    deadline: datetime | None = None,
    ensure_progress: bool = True,
) -> SyncResult | SyncPartial | SyncPaused | SyncAlreadyRunning | SyncUserGone:
    """Sync one user. Raises SyncRevoked or SyncFailed after recording the state.

    One sync per user: a lease row in sync_state is claimed atomically at `now` and extended
    after each committed batch using `clock` (default: the real UTC clock, so long syncs keep
    their lease; tests pass a fake clock). `force` reprocesses threads even when unchanged.
    `deadline` (compared with `clock`) stops the run between batches (and between threads) with
    SyncPartial. A rate limit Gmail will not lift within the call's retries pauses the run
    (SyncPaused, state "paused"); after MAX_CONSECUTIVE_RATE_LIMITS in a row it is an error
    (SyncFailed). `ensure_progress` (default) completes one batch first; a manual run passes False.
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
        deadline,
        ensure_progress,
    )
    try:
        state = _claim(ctx)
    except _UserGone:
        return SyncUserGone()
    if state is None:
        return SyncAlreadyRunning()
    ctx.state = state
    return _run_claimed(ctx)
