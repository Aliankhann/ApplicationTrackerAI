"""Gmail data carried through the app. Metadata only: no bodies, no To/Cc fields."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ThreadSummary:
    thread_id: str
    history_id: str


@dataclass(frozen=True)
class MessageMeta:
    message_id: str
    thread_id: str
    from_address: str
    from_name: str
    subject: str
    snippet: str
    sent_at: datetime  # timezone-aware UTC
    from_user: bool  # sent by the mailbox owner
    rfc822_message_id: str | None
    label_ids: frozenset[str] = frozenset()  # e.g. INBOX, SENT, DRAFT

    def __post_init__(self) -> None:
        if self.sent_at.tzinfo is None:
            raise ValueError("sent_at must be timezone-aware")

    @property
    def is_draft(self) -> bool:
        return "DRAFT" in self.label_ids


@dataclass(frozen=True)
class ThreadMeta:
    thread_id: str
    history_id: str
    messages: tuple[MessageMeta, ...]  # chronological, never empty

    @property
    def last_message(self) -> MessageMeta:
        return self.messages[-1]

    @property
    def first_message_at(self) -> datetime:
        return self.messages[0].sent_at

    @property
    def last_message_at(self) -> datetime:
        return self.messages[-1].sent_at

    @property
    def message_count(self) -> int:
        return len(self.messages)

    @property
    def last_sender_is_user(self) -> bool:
        return self.messages[-1].from_user


@dataclass(frozen=True)
class HistoryPage:
    history_id: str
    changed_thread_ids: tuple[str, ...]
    next_page_token: str | None


@dataclass(frozen=True)
class Profile:
    email: str
    history_id: str


@dataclass(frozen=True)
class DraftRequest:
    thread_id: str
    in_reply_to: str
    references: str
    subject: str
    body_text: str
    to: str = ""  # fetched at draft time; never stored or logged


@dataclass(frozen=True)
class DraftRef:
    draft_id: str
