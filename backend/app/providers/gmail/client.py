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

    def get_profile(self) -> Profile: ...

    def list_threads(
        self, query: str, page_token: str | None = None
    ) -> tuple[list[ThreadSummary], str | None]: ...

    def get_thread(self, thread_id: str) -> ThreadMeta: ...

    def get_threads(self, thread_ids: list[str]) -> list[ThreadMeta]:
        """Batch fetch; raises GmailNotFound if any id is missing."""
        ...

    def list_history(self, start_history_id: str, page_token: str | None = None) -> HistoryPage: ...

    def get_reply_recipient(self, thread_id: str) -> str:
        """Fetched at draft time, never stored."""
        ...

    def create_draft(self, request: DraftRequest) -> DraftRef: ...

    def get_draft(self, draft_id: str) -> DraftRef | None:
        """None when the draft no longer exists (deleted or sent)."""
        ...
