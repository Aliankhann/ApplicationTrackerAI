"""In-memory GmailClient for tests. Never talks to Google."""

import re
from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from app.providers.gmail.errors import (
    GmailAuthRevoked,
    GmailError,
    GmailHistoryExpired,
    GmailNotFound,
    GmailRateLimited,
)
from app.providers.gmail.types import (
    DraftRef,
    DraftRequest,
    HistoryPage,
    MessageMeta,
    Profile,
    ThreadMeta,
    ThreadSummary,
)

_NEWER_THAN = re.compile(r"newer_than:(\d+)d")
_SNIPPET_MAX = 200


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value


def _parse_int(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise GmailNotFound("invalid id or page token") from None


class FakeGmailClient:
    """Only the `newer_than:Nd` query term is honoured; all other terms are ignored.

    Snippets are stored as given by add_message: truncation is the sync layer's job.
    Fault injection: `revoke()` wins over `fail_next`; `fail_next` is a single slot
    (a second call replaces the pending error) and fires once on the next call.
    """

    def __init__(
        self,
        owner_email: str,
        threads: dict[str, list[MessageMeta]] | None = None,
        *,
        now: datetime | None = None,
        page_size: int = 100,
        history_floor: int = 0,
        initial_history_id: int = 1000,
    ) -> None:
        if any(not msgs for msgs in (threads or {}).values()):
            raise ValueError("threads must not be empty")
        self.owner_email = owner_email
        self.now = _require_aware(now) if now else datetime.now(UTC)
        self.page_size = page_size
        self.history_floor = history_floor
        self._drafts: list[DraftRequest] = []
        self._threads: dict[str, list[MessageMeta]] = {
            tid: sorted(msgs, key=lambda m: m.sent_at) for tid, msgs in (threads or {}).items()
        }
        self._history_id = initial_history_id
        self._changes: list[tuple[int, str]] = []
        self._snapshots: dict[int, list[str]] = {}
        self._thread_history: dict[str, int] = dict.fromkeys(self._threads, initial_history_id)
        self._draft_messages: dict[str, tuple[str, str]] = {}  # draft_id -> (thread, message)
        self._message_seq = 0
        self._revoked = False
        self._next_error: GmailError | None = None
        self._rate_limited: dict[str, int | None] = {}  # thread id -> fetches left to refuse
        self.rate_limit_hits = 0
        self.fetched_thread_ids: list[str] = []  # every thread successfully returned, in order

    @property
    def drafts(self) -> tuple[DraftRequest, ...]:
        return tuple(self._drafts)

    # Fault injection

    def revoke(self) -> None:
        self._revoked = True

    def fail_next(self, exc: GmailError) -> None:
        self._next_error = exc

    def rate_limit_threads(self, thread_ids: Iterable[str], times: int | None = None) -> None:
        """Refuse these threads as rate limited `times` fetches each (None: until cleared)."""
        self._rate_limited.update(dict.fromkeys(thread_ids, times))

    def clear_rate_limits(self) -> None:
        self._rate_limited.clear()

    def _limited(self, thread_id: str) -> bool:
        if thread_id not in self._rate_limited:
            return False
        left = self._rate_limited[thread_id]
        if left is not None:
            if left <= 1:
                del self._rate_limited[thread_id]
            else:
                self._rate_limited[thread_id] = left - 1
        self.rate_limit_hits += 1
        return True

    def _guard(self) -> None:
        if self._revoked:
            raise GmailAuthRevoked
        if self._next_error is not None:
            exc, self._next_error = self._next_error, None
            raise exc

    # Test setup

    def _record(self, thread_id: str, message: MessageMeta) -> MessageMeta:
        messages = self._threads.setdefault(thread_id, [])
        messages.append(message)
        messages.sort(key=lambda m: m.sent_at)
        self._bump(thread_id)
        return message

    def _bump(self, thread_id: str) -> None:
        self._history_id += 1
        self._thread_history[thread_id] = self._history_id
        self._changes.append((self._history_id, thread_id))

    def _new_message(
        self,
        thread_id: str,
        *,
        from_address: str,
        subject: str,
        snippet: str,
        sent_at: datetime,
        from_name: str,
        from_user: bool,
        rfc822_message_id: str | None,
        label_ids: frozenset[str],
    ) -> MessageMeta:
        self._message_seq += 1
        return MessageMeta(
            message_id=f"fake-m{self._message_seq}",
            thread_id=thread_id,
            from_address=from_address,
            from_name=from_name,
            subject=subject,
            snippet=snippet,
            sent_at=sent_at,
            from_user=from_user,
            rfc822_message_id=rfc822_message_id,
            label_ids=label_ids,
        )

    def add_message(
        self,
        thread_id: str,
        *,
        from_address: str,
        subject: str = "",
        snippet: str = "",
        sent_at: datetime | None = None,
        from_name: str = "",
        from_user: bool = False,
        rfc822_message_id: str | None = None,
        label_ids: frozenset[str] | None = None,
    ) -> MessageMeta:
        message = self._new_message(
            thread_id,
            from_address=from_address,
            subject=subject,
            snippet=snippet,
            sent_at=_require_aware(sent_at) if sent_at else self.now,
            from_name=from_name,
            from_user=from_user,
            rfc822_message_id=rfc822_message_id,
            label_ids=label_ids
            if label_ids is not None
            else frozenset({"SENT" if from_user else "INBOX"}),
        )
        return self._record(thread_id, message)

    def send_draft(self, draft_id: str) -> None:
        """Turn a draft into a SENT message (removes the DRAFT label) and bump history."""
        thread_id, message_id = self._draft_messages.pop(draft_id)
        messages = self._threads[thread_id]
        for i, message in enumerate(messages):
            if message.message_id == message_id:
                labels = (message.label_ids - {"DRAFT"}) | {"SENT"}
                messages[i] = replace(message, label_ids=labels)
        self._bump(thread_id)

    def delete_draft(self, draft_id: str) -> None:
        thread_id, message_id = self._draft_messages.pop(draft_id)
        self._threads[thread_id] = [
            m for m in self._threads[thread_id] if m.message_id != message_id
        ]
        self._bump(thread_id)

    # GmailClient

    def get_profile(self) -> Profile:
        self._guard()
        return Profile(email=self.owner_email, history_id=str(self._history_id))

    def list_threads(
        self, query: str, page_token: str | None = None
    ) -> tuple[list[ThreadSummary], str | None]:
        self._guard()
        match = _NEWER_THAN.search(query)
        cutoff = self.now - timedelta(days=int(match.group(1))) if match else None
        live = [(tid, msgs) for tid, msgs in self._threads.items() if msgs]
        ordered = sorted(live, key=lambda item: (-item[1][-1].sent_at.timestamp(), item[0]))
        ids = [tid for tid, msgs in ordered if cutoff is None or msgs[-1].sent_at >= cutoff]
        start = _parse_int(page_token) if page_token else 0
        end = start + self.page_size
        page = [ThreadSummary(tid, str(self._thread_history[tid])) for tid in ids[start:end]]
        return page, str(end) if end < len(ids) else None

    def _thread(self, thread_id: str) -> ThreadMeta:
        if not self._threads.get(thread_id):
            raise GmailNotFound(thread_id)
        return ThreadMeta(
            thread_id=thread_id,
            history_id=str(self._thread_history[thread_id]),
            messages=tuple(self._threads[thread_id]),
        )

    def get_thread(self, thread_id: str) -> ThreadMeta:
        self._guard()
        if self._limited(thread_id):
            raise GmailRateLimited
        found = self._thread(thread_id)
        self.fetched_thread_ids.append(thread_id)
        return found

    def get_threads(self, thread_ids: list[str]) -> list[ThreadMeta]:
        """Like the real client: threads that stay rate limited raise with the rest attached."""
        self._guard()
        found: list[ThreadMeta] = []
        limited = False
        for tid in thread_ids:
            if self._limited(tid):
                limited = True
                continue
            found.append(self._thread(tid))
            self.fetched_thread_ids.append(tid)
        if limited:
            raise GmailRateLimited(fetched=tuple(found))
        return found

    def list_history(self, start_history_id: str, page_token: str | None = None) -> HistoryPage:
        self._guard()
        start = _parse_int(start_history_id)
        if start > self._history_id:
            raise GmailNotFound(start_history_id)
        if start < self.history_floor:
            raise GmailHistoryExpired(start_history_id)
        if page_token is None:
            snapshot_id = len(self._snapshots)
            changed = list(dict.fromkeys(tid for hid, tid in self._changes if hid > start))
            self._snapshots[snapshot_id] = changed
            offset = 0
        else:
            snap, _, off = page_token.partition(":")
            snapshot_id, offset = _parse_int(snap), _parse_int(off)
            if snapshot_id not in self._snapshots:
                raise GmailNotFound("invalid page token")
            changed = self._snapshots[snapshot_id]
        end = offset + self.page_size
        return HistoryPage(
            history_id=str(self._history_id),
            changed_thread_ids=tuple(changed[offset:end]),
            next_page_token=f"{snapshot_id}:{end}" if end < len(changed) else None,
        )

    def get_reply_recipient(self, thread_id: str) -> str:
        self._guard()
        for message in reversed(self._thread(thread_id).messages):
            if not message.from_user:
                return message.from_address
        raise GmailNotFound(thread_id)

    def create_draft(self, request: DraftRequest) -> DraftRef:
        self._guard()
        self._thread(request.thread_id)
        self._drafts.append(request)
        message = self._new_message(
            request.thread_id,
            from_address=self.owner_email,
            subject=request.subject,
            snippet=request.body_text[:_SNIPPET_MAX],
            sent_at=self.now,
            from_name="",
            from_user=True,
            rfc822_message_id=None,
            label_ids=frozenset({"DRAFT"}),
        )
        self._record(request.thread_id, message)
        draft_id = f"fake-d{len(self._drafts)}"
        self._draft_messages[draft_id] = (request.thread_id, message.message_id)
        return DraftRef(draft_id=draft_id)

    def get_draft(self, draft_id: str) -> DraftRef | None:
        self._guard()
        return DraftRef(draft_id) if draft_id in self._draft_messages else None
