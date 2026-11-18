"""Tables: users, tokens, invites, threads, applications. See docs/build-plan.md#data-model."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
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
)
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
    updated_at: Mapped[datetime] = _updated_at()


class Classification(TimestampMixin, Base):
    """Append-only history; the latest row by created_at is current."""

    __tablename__ = "classifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
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
