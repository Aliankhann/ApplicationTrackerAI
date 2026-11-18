"""Tables: users, tokens, invites, threads, applications, sync state (docs/build-plan.md)."""

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin
from app.providers.classifier.types import Label
from app.services.classification import ApplicationStatus


class TokenStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    google_sub: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    timezone: Mapped[str | None] = mapped_column(String(64))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    digest_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class OAuthToken(TimestampMixin, Base):
    """Refresh tokens are stored AES-GCM encrypted; plaintext never touches the database."""

    __tablename__ = "oauth_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    refresh_token_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    scopes: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[TokenStatus] = mapped_column(
        Enum(TokenStatus, name="token_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=TokenStatus.ACTIVE,
    )


class InviteCode(TimestampMixin, Base):
    """Only a hash of the code is stored, never the code itself."""

    __tablename__ = "invite_codes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    created_for_email: Mapped[str | None] = mapped_column(String(320))
    used_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RateLimit(Base):
    """Fixed-window counters shared by all instances. Keys are HMACs, never raw IPs."""

    __tablename__ = "rate_limits"

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


def _values(enum_cls: type[StrEnum]) -> list[str]:
    return [m.value for m in enum_cls]


def _updated_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class EmailThread(TimestampMixin, Base):
    """Metadata only: never bodies or recipient addresses; the snippet is capped at 200 chars."""

    __tablename__ = "email_threads"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "gmail_thread_id", name="uq_email_threads_user_id_gmail_thread_id"
        ),
        Index("ix_email_threads_user_id_last_message_at", "user_id", "last_message_at"),
        CheckConstraint("char_length(snippet) <= 200", name="snippet_max_200"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    gmail_thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    subject: Mapped[str] = mapped_column(String(998), nullable=False)
    from_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    snippet: Mapped[str] = mapped_column(String(200), nullable=False)
    first_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_sender_is_user: Mapped[bool] = mapped_column(Boolean, nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False)
    pipeline_version: Mapped[str] = mapped_column(
        String(16), nullable=False, default="0", server_default="0"
    )
    updated_at: Mapped[datetime] = _updated_at()


class Classification(TimestampMixin, Base):
    """Append-only history; the latest row by seq is current (created_at ties within a txn)."""

    __tablename__ = "classifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False)
    thread_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("email_threads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[Label | None] = mapped_column(
        Enum(Label, name="classification_label", values_callable=_values)
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    rule_id: Mapped[str | None] = mapped_column(String(64))
    model_version: Mapped[str | None] = mapped_column(String(64))
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False)


class Application(TimestampMixin, Base):
    __tablename__ = "applications"
    __table_args__ = (
        Index("ix_applications_user_id_status", "user_id", "status"),
        Index("ix_applications_user_id_last_activity_at", "user_id", "last_activity_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    company: Mapped[str | None] = mapped_column(String(80))
    role: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus, name="application_status", values_callable=_values),
        nullable=False,
    )
    source_thread_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("email_threads.id", ondelete="SET NULL"), unique=True
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    followups_paused: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    updated_at: Mapped[datetime] = _updated_at()


class StatusEvent(Base):
    __tablename__ = "status_events"
    __table_args__ = (Index("ix_status_events_application_id_at", "application_id", "at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[ApplicationStatus | None] = mapped_column(
        Enum(ApplicationStatus, name="application_status", values_callable=_values)
    )
    to_status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus, name="application_status", values_callable=_values),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SyncStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    ERROR = "error"
    REVOKED = "revoked"


class SyncState(TimestampMixin, Base):
    """One row per user. `last_error` is a stable code, never exception text.

    A running sync holds a lease (`lease_expires_at`); an expired lease means it crashed.
    """

    __tablename__ = "sync_state"
    __table_args__ = (
        CheckConstraint("status in ('idle', 'running', 'error', 'revoked')", name="status_valid"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    history_id: Mapped[str | None] = mapped_column(String(32))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    initial_sync_done: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SyncStatus.IDLE.value, server_default="idle"
    )
    last_error: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = _updated_at()


class Sequence(TimestampMixin, Base):
    """A user's follow-up plan. `steps` holds validated step dicts; one default per user."""

    __tablename__ = "sequences"
    __table_args__ = (
        Index(
            "uq_sequences_user_id_default",
            "user_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
        CheckConstraint("tone in ('short', 'warm', 'formal')", name="tone_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    steps: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    tone: Mapped[str] = mapped_column(
        String(16), nullable=False, default="short", server_default="short"
    )
    updated_at: Mapped[datetime] = _updated_at()


class FollowUpTask(TimestampMixin, Base):
    """One scheduled step per application. Never stores rendered bodies or recipients."""

    __tablename__ = "follow_up_tasks"
    __table_args__ = (
        UniqueConstraint(
            "application_id", "step_index", name="uq_follow_up_tasks_application_id_step_index"
        ),
        Index("ix_follow_up_tasks_state_due_at", "state", "due_at"),
        CheckConstraint(
            "state in ('pending', 'drafting', 'drafted', 'sent', 'cancelled', 'skipped')",
            name="state_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    sequence_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sequences.id", ondelete="SET NULL")
    )
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    gmail_draft_id: Mapped[str | None] = mapped_column(String(128))
    cancel_reason: Mapped[str | None] = mapped_column(String(32))
    drafted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    updated_at: Mapped[datetime] = _updated_at()


class SchedulerState(TimestampMixin, Base):
    """One row per user: the lease that keeps two run_due workers off the same user."""

    __tablename__ = "scheduler_state"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(Base):
    """Server-side login session. Only the SHA-256 of the cookie token is stored."""

    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_user_id", "user_id"),
        Index("ix_sessions_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    csrf_secret: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent_hash: Mapped[str | None] = mapped_column(String(64))


class AuditAction(StrEnum):
    """Login and gmail_connected arrive with US-11/US-31; data_exported is reserved (CSV export)."""

    LOGIN = "login"
    LOGOUT = "logout"
    GMAIL_CONNECTED = "gmail_connected"
    GMAIL_DISCONNECTED = "gmail_disconnected"
    ACCOUNT_DELETED = "account_deleted"
    FOLLOWUPS_ENABLED = "followups_enabled"
    DATA_EXPORTED = "data_exported"


class AuditLog(Base):
    """Who did what and when, nothing else: no IP, user agent, email, or content.

    `user_id` is deliberately NOT a foreign key: it is a random uuid with no personal data, so
    entries can outlive an account. Deleting an account removes that user's rows and writes one
    anonymous `account_deleted` row with `user_id` NULL.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_user_id", "user_id"),
        Index("ix_audit_log_at", "at"),
        CheckConstraint(
            "action in ('login', 'logout', 'gmail_connected', 'gmail_disconnected', "
            "'account_deleted', 'followups_enabled', 'data_exported')",
            name="action_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DigestLog(Base):
    """One row per user and local date: the unique key makes the daily digest send at most once.

    `claimed_at` is when the current attempt started; a 'sending' row that stays stale means the
    process died around the send, so the outcome is unknown and it is never resent.
    """

    __tablename__ = "digest_log"
    __table_args__ = (
        UniqueConstraint("user_id", "digest_date", name="uq_digest_log_user_id_digest_date"),
        CheckConstraint(
            "status in ('sending', 'sent', 'failed', 'skipped_empty')", name="status_valid"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    digest_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
