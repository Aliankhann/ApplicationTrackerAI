from collections.abc import Callable
from typing import Protocol

from app.providers.gmail.types import (
    DraftRef,
    DraftRequest,
    HistoryPage,
    Profile,
    ThreadMeta,
    ThreadSummary,
)


class GmailClient(Protocol):
    """All Gmail access goes through this interface; tests use FakeGmailClient."""

    rate_limit_hits: int  # rate-limit responses seen so far (a count, for logging)

    def get_profile(self) -> Profile: ...

    def list_threads(
        self, query: str, page_token: str | None = None
    ) -> tuple[list[ThreadSummary], str | None]: ...

    def get_thread(self, thread_id: str) -> ThreadMeta: ...

    def get_threads(
        self, thread_ids: list[str], time_left: Callable[[], float | None] | None = None
    ) -> list[ThreadMeta]:
        """Batch fetch in id order; deleted threads are left out. Rate-limited threads are
        retried alone, within `time_left` seconds when given. Raises GmailRateLimited (carrying
        the threads it did fetch) if some stay rate limited."""
        ...

    def list_history(self, start_history_id: str, page_token: str | None = None) -> HistoryPage: ...

    def get_reply_recipient(self, thread_id: str) -> str:
        """Fetched at draft time, never stored."""
        ...

    def create_draft(self, request: DraftRequest) -> DraftRef: ...

    def get_draft(self, draft_id: str) -> DraftRef | None:
        """None when the draft no longer exists (deleted or sent)."""
        ...
