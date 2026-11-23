"""Follow-up scheduler: plans steps as tasks and turns due ones into Gmail drafts. Never sends.

Concurrency: a per-user lease (scheduler_state) admits one run_due at a time, and each task is
claimed (pending -> drafting) and committed before any Gmail call, so a crash can never lead to
a second draft: stale claims are cancelled as `uncertain_draft` when a draft may exist.

Known limit: edited drafts are not detected. A Gmail draft id survives edits, so reconciliation
only notices a draft once it is cleared (sent or deleted), then looks for a new SENT message.
"""

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.config import get_settings
from app.log import get_logger
from app.models import Application, EmailThread, FollowUpTask, User
from app.providers.gmail.client import GmailClient
from app.providers.gmail.errors import (
    GmailAuthRevoked,
    GmailError,
    GmailNotFound,
    GmailRateLimited,
)
from app.providers.gmail.types import DraftRequest, MessageMeta, ThreadMeta
from app.providers.google.scopes import can_compose
from app.repositories import applications as applications_repo
from app.repositories import followups as repo
from app.repositories import oauth_tokens as tokens_repo
from app.repositories import sequences as sequences_repo
from app.services import followup_policy as policy
from app.services.followup_policy import Decision, StopReason
from app.services.sequences import Step, parse_stored_steps
from app.services.templates import Tone, format_applied_date, render, subject_for

logger = get_logger("app.scheduler")

_NAME = re.compile(r"^[A-Z][a-z'\u2019-]{1,29}$")
_NOT_NAMES = frozenset(
    {"careers", "career", "recruiting", "recruiter", "talent", "team", "hr", "jobs", "hiring"}
    | {"noreply", "greenhouse", "lever", "workday", "icims", "taleo", "smartrecruiters", "ashby"}
    | {"jobvite", "bamboohr", "workable", "linkedin", "indeed", "handshake", "myworkday"}
)
MAX_FAILURES = 3
STALE_CLAIM = timedelta(minutes=15)


@dataclass
class RunResult:
    drafted: int = 0
    cancelled: int = 0
    skipped_window: int = 0
    skipped_cap: int = 0
    waiting_earlier_step: int = 0
    already_running: bool = False  # another run_due holds this user's lease
    no_compose: bool = False  # the live token lacks gmail.compose: follow-ups are not turned on


def user_timezone(user: User) -> ZoneInfo:
    default = get_settings().default_timezone
    try:
        return ZoneInfo(user.timezone or default)
    except ZoneInfoNotFoundError:
        return ZoneInfo(default)


def _load_user(session: Session, user_id: uuid.UUID) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise LookupError("user not found")
    return user


def plan_followups(session: Session, user_id: uuid.UUID, now: datetime) -> int:
    """Create missing tasks for every step of the default sequence; returns how many were new.

    Steps already overdue by more than `followup_stale_days` are created as skipped."""
    user = _load_user(session, user_id)
    tz = user_timezone(user)
    sequence = sequences_repo.get_or_create_default(session, user_id)
    steps = parse_stored_steps(sequence.steps)
    if steps is None:
        return 0
    created = 0
    stale_after = timedelta(days=get_settings().followup_stale_days)
    for application, thread in repo.plannable(session, user_id):
        base = application.applied_at or thread.first_message_at
        for index, step in enumerate(steps):
            due = policy.due_at_for(base, step.delay_days, tz, get_settings().followup_window_mode)
            stale = due < now - stale_after
            created += repo.insert_if_absent(
                session,
                application.id,
                sequence.id,
                index,
                due,
                now,
                state=repo.SKIPPED if stale else repo.PENDING,
                cancel_reason=StopReason.STALE_ON_PLAN.value if stale else None,
            )
    session.flush()
    return created


def _first_name(thread: ThreadMeta, company: str | None) -> str | None:
    """First token of the last external sender's name, only when it is clearly a person."""
    for message in reversed(policy.real_messages(thread)):
        if message.from_user:
            continue
        tokens = message.from_name.split()
        if len(tokens) < 2 or not _NAME.match(tokens[0]):
            return None
        blocked = _NOT_NAMES | set((company or "").lower().split())
        return None if any(t.lower() in blocked for t in tokens) else tokens[0]
    return None


def _build_request(
    task_step: Step,
    tone: Tone,
    application: Application,
    row: EmailThread,
    thread: ThreadMeta,
    tz: ZoneInfo,
    recipient: str,
) -> DraftRequest:
    real = policy.real_messages(thread)
    ids = [m.rfc822_message_id for m in real if m.rfc822_message_id]
    context = {
        "recruiter_first_name": _first_name(thread, application.company),
        "role": application.role,
        "company": application.company,
        "applied_date": format_applied_date(application.applied_at or row.first_message_at, tz),
        "your_name": None,  # no profile name is stored yet
    }
    return DraftRequest(
        thread_id=thread.thread_id,
        in_reply_to=ids[-1] if ids else "",
        references=" ".join(ids),
        subject=subject_for(row.subject),
        body_text=render(task_step.template, context, tone),
        to=recipient,
    )


@dataclass
class _Run:
    session: Session
    user_id: uuid.UUID
    client: GmailClient
    now: datetime
    commit: Callable[[], None]
    tz: ZoneInfo
    result: RunResult
    user_email: str
    clock: Callable[[], datetime]
    sequences: dict[uuid.UUID, tuple[list[Step], Tone]]

    def cancel_from(
        self,
        application_id: uuid.UUID | None,
        reason: StopReason,
        from_step: int = 0,
        extra: int = 0,
    ) -> None:
        count = extra + repo.cancel_pending(
            self.session,
            self.user_id,
            reason.value,
            application_id=application_id,
            from_step=from_step,
        )
        self.result.cancelled += count
        self.commit()
        logger.info(
            "followup.cancelled",
            extra={"user_id": self.user_id, "error_code": reason.value, "count": count},
        )


def _sequence_for(run: _Run, task: FollowUpTask) -> tuple[list[Step], Tone]:
    sequence_id = (
        task.sequence_id or sequences_repo.get_or_create_default(run.session, run.user_id).id
    )
    if sequence_id not in run.sequences:
        sequence = sequences_repo.get(run.session, run.user_id, sequence_id)
        steps = parse_stored_steps(sequence.steps) or []
        run.sequences[sequence_id] = (steps, cast(Tone, sequence.tone))
    return run.sequences[sequence_id]


def _since(run: _Run, task: FollowUpTask) -> datetime:
    last_sent = repo.latest_sent_at(run.session, run.user_id, task.application_id)
    return max(task.created_at, last_sent) if last_sent else task.created_at


def _stop_reason(
    run: _Run, task: FollowUpTask, application: Application, thread: ThreadMeta, steps: list[Step]
) -> StopReason | None:
    """A step missing from the (edited) sequence counts as attempts exhausted."""
    attempts = repo.count_attempts(run.session, run.user_id, application.id)
    limit = sum(s.max_attempts for s in steps) if task.step_index < len(steps) else 0
    return policy.should_stop(
        application.status,
        thread,
        since=_since(run, task),
        paused=application.followups_paused,
        attempts=attempts,
        max_attempts=limit,
        gmail_revoked=repo.gmail_revoked(run.session, run.user_id),
    )


def _release(run: _Run, task: FollowUpTask, *, failed: bool = False) -> int:
    """Put a claimed task back to pending; returns its failure count."""
    if task.state == repo.DRAFTING:
        task.state = repo.PENDING
        task.claimed_at = None
    if failed:
        task.attempt_failures += 1
    run.session.flush()
    return task.attempt_failures


def _draft(run: _Run, task: FollowUpTask, application: Application, row: EmailThread) -> None:
    """Runs on a claimed task; every non-draft outcome leaves it pending or cancelled."""
    thread = run.client.get_thread(row.gmail_thread_id)
    steps, tone = _sequence_for(run, task)
    reason = _stop_reason(run, task, application, thread, steps)
    if reason is StopReason.GMAIL_DISCONNECTED:
        raise GmailAuthRevoked
    recipient = ""
    if reason is None:
        recipient = run.client.get_reply_recipient(row.gmail_thread_id)
        reason = policy.recipient_stop(recipient, run.user_email)
    if reason is not None:
        _release(run, task)
        run.cancel_from(application.id, reason, task.step_index)
        return
    request = _build_request(
        steps[task.step_index], tone, application, row, thread, run.tz, recipient
    )
    task.gmail_draft_id = run.client.create_draft(request).draft_id
    task.state = repo.DRAFTED
    task.drafted_at = run.now
    run.commit()
    run.result.drafted += 1
    logger.info("followup.drafted", extra={"user_id": run.user_id, "count": 1})


def _attempt(run: _Run, task: FollowUpTask, application: Application, row: EmailThread) -> None:
    """Claim the task, draft it, and contain per-task Gmail failures."""
    if not repo.claim_task(run.session, task.id, run.now):
        return
    run.commit()
    try:
        _draft(run, task, application, row)
    except (GmailAuthRevoked, GmailRateLimited):
        _release(run, task)
        raise
    except GmailNotFound:
        _release(run, task)
        run.cancel_from(application.id, StopReason.THREAD_MISSING, task.step_index)
    except GmailError as exc:
        failures = _release(run, task, failed=True)
        logger.warning(
            "followup.task_failed",
            extra={"user_id": run.user_id, "error_code": type(exc).__name__, "count": failures},
        )
        if failures >= MAX_FAILURES:
            run.cancel_from(application.id, StopReason.GMAIL_ERROR, task.step_index)
        else:
            run.commit()


def _draft_due(run: _Run, due: list[FollowUpTask]) -> None:
    cap = get_settings().followup_daily_draft_cap
    start, end = policy.local_day_bounds(run.now, run.tz)
    already = repo.count_drafted_between(run.session, run.user_id, start, end)
    for task in due:
        if task.state != repo.PENDING:  # cancelled earlier in this run
            continue
        if repo.has_earlier_open(run.session, run.user_id, task.application_id, task.step_index):
            run.result.waiting_earlier_step += 1  # keep step order: wait for the earlier step
            continue
        if (
            policy.decide(
                run.now,
                run.tz,
                already + run.result.drafted,
                cap,
                get_settings().followup_window_mode,
            )
            is Decision.SKIP_CAP
        ):
            run.result.skipped_cap = sum(1 for t in due if t.state == repo.PENDING)
            return
        repo.renew_lease(run.session, run.user_id, run.clock() + _lease_ttl())
        application = applications_repo.get(run.session, run.user_id, task.application_id)
        row = _source_thread(run, application)
        if application is None or row is None:
            run.cancel_from(task.application_id, StopReason.THREAD_MISSING, task.step_index)
            continue
        if repo.has_drafted(run.session, run.user_id, application.id):
            continue
        _attempt(run, task, application, row)


def _lease_ttl() -> timedelta:
    return timedelta(minutes=get_settings().scheduler_lease_minutes)


def _source_thread(run: _Run, application: Application | None) -> EmailThread | None:
    if application is None or application.source_thread_id is None:
        return None
    return repo.thread_for(run.session, run.user_id, application.source_thread_id)


def _resolve_stale_claims(run: _Run) -> None:
    """A claim older than STALE_CLAIM means a worker died mid-draft. If a user DRAFT appeared
    after the claim we cannot tell which draft id is ours, so cancel rather than risk two."""
    for task in repo.stale_drafting(run.session, run.user_id, run.now - STALE_CLAIM):
        application = applications_repo.get(run.session, run.user_id, task.application_id)
        row = _source_thread(run, application)
        claimed = task.claimed_at
        try:
            thread = run.client.get_thread(row.gmail_thread_id) if row and claimed else None
        except GmailNotFound:
            thread = None
        found = (
            thread is not None
            and claimed is not None
            and any(
                m.from_user and m.is_draft and m.sent_at >= claimed - CLAIM_CLOCK_SLACK
                for m in thread.messages
            )
        )
        if found:
            task.state = repo.CANCELLED
            task.cancel_reason = StopReason.UNCERTAIN_DRAFT.value
            # A draft probably exists, so it still counts toward today's cap.
            task.drafted_at = claimed
            run.cancel_from(
                task.application_id, StopReason.UNCERTAIN_DRAFT, task.step_index + 1, extra=1
            )
        else:
            _release(run, task)
            run.commit()


def _user_sent_after(thread: ThreadMeta, moment: datetime) -> MessageMeta | None:
    sent = [m for m in policy.real_messages(thread) if m.from_user and m.sent_at >= moment]
    return sent[0] if sent else None


def _reconcile_one(run: _Run, task: FollowUpTask) -> None:
    if task.gmail_draft_id and run.client.get_draft(task.gmail_draft_id) is not None:
        return
    application = applications_repo.get(run.session, run.user_id, task.application_id)
    row = (
        repo.thread_for(run.session, run.user_id, application.source_thread_id)
        if application is not None and application.source_thread_id
        else None
    )
    sent = None
    if row is not None and task.drafted_at is not None:
        try:
            sent = _user_sent_after(run.client.get_thread(row.gmail_thread_id), task.drafted_at)
        except GmailNotFound:
            sent = None
    if sent is not None:
        task.state = repo.SENT
        task.sent_at = sent.sent_at
        run.commit()
        return
    task.state = repo.CANCELLED
    task.cancel_reason = StopReason.DRAFT_EDITED_OR_SENT.value
    run.cancel_from(
        task.application_id, StopReason.DRAFT_EDITED_OR_SENT, task.step_index + 1, extra=1
    )


def _reconcile(run: _Run) -> None:
    for task in repo.in_state(run.session, run.user_id, repo.DRAFTED):
        _reconcile_one(run, task)


# Gmail's clock and ours may differ; err toward treating a draft as ours (safe: cancel).
CLAIM_CLOCK_SLACK = timedelta(seconds=60)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def run_due(
    session: Session,
    user_id: uuid.UUID,
    client: GmailClient,
    now: datetime,
    commit: Callable[[], None] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> RunResult:
    """Reconcile existing drafts, then draft due steps inside the send window. Never sends.

    `clock` supplies the time used to renew the lease during a long run (default: the real
    UTC clock; tests pass a fake clock).
    """
    user = _load_user(session, user_id)
    commit = commit or session.commit
    token = tokens_repo.active_row(session, user_id)
    if token is not None and not can_compose(token.scopes):
        return RunResult(no_compose=True)  # never draft without the compose grant
    if not repo.claim_lease(session, user_id, now, _lease_ttl()):
        commit()
        return RunResult(already_running=True)
    commit()
    run = _Run(
        session,
        user_id,
        client,
        now,
        commit,
        user_timezone(user),
        RunResult(),
        user.email,
        clock or _utcnow,
        {},
    )
    try:
        _resolve_stale_claims(run)
        _reconcile(run)
        due = repo.due_pending(session, user_id, now)
        if not policy.in_send_window(now, run.tz, get_settings().followup_window_mode):
            run.result.skipped_window = len(due)
        else:
            _draft_due(run, due)
    except GmailAuthRevoked:
        run.cancel_from(None, StopReason.GMAIL_DISCONNECTED)
    except GmailRateLimited:
        logger.warning("followup.rate_limited", extra={"user_id": user_id})
    except Exception:
        session.rollback()
        if session.get(User, user_id) is None:  # account deleted mid-run: stop cleanly
            return run.result
        raise
    finally:
        repo.release_lease(session, user_id)
        commit()
    return run.result
