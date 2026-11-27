"""Thread metadata and classification history. Every query is scoped by user_id."""

import uuid
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.errors import NotFound
from app.models import Classification, EmailThread
from app.providers.classifier.types import ClassificationResult
from app.providers.gmail.types import MessageMeta, ThreadMeta

MAX_SNIPPET = 200
MAX_DOMAIN = 255
MAX_SUBJECT = 998


def _counted_messages(meta: ThreadMeta) -> tuple[MessageMeta, ...]:
    """Messages without drafts; a draft-only thread falls back to all its messages."""
    sent = tuple(m for m in meta.messages if not m.is_draft)
    return sent or meta.messages


def get_by_gmail_id(
    session: Session, user_id: uuid.UUID, gmail_thread_id: str
) -> EmailThread | None:
    stmt = select(EmailThread).where(
        EmailThread.user_id == user_id, EmailThread.gmail_thread_id == gmail_thread_id
    )
    return session.scalars(stmt).one_or_none()


def is_unchanged(thread: EmailThread, meta: ThreadMeta, pipeline_version: str) -> bool:
    """True when the row reflects the current messages and was built by this pipeline version."""
    messages = _counted_messages(meta)
    return (
        thread.message_count == len(messages)
        and thread.last_message_at == messages[-1].sent_at
        and thread.pipeline_version == pipeline_version
    )


def upsert_thread(
    session: Session,
    user_id: uuid.UUID,
    meta: ThreadMeta,
    subject: str,
    from_domain: str,
    snippet: str,
    pipeline_version: str = "0",
) -> EmailThread:
    """Idempotent on (user_id, gmail_thread_id). Drafts never count as the last message."""
    messages = _counted_messages(meta)
    values = {
        "subject": subject[:MAX_SUBJECT],
        "from_domain": from_domain[:MAX_DOMAIN],
        "snippet": snippet[:MAX_SNIPPET],
        "first_message_at": messages[0].sent_at,
        "last_message_at": messages[-1].sent_at,
        "last_sender_is_user": messages[-1].from_user,
        "message_count": len(messages),
        "pipeline_version": pipeline_version,
    }
    stmt = (
        insert(EmailThread)
        .values(user_id=user_id, gmail_thread_id=meta.thread_id, **values)
        .on_conflict_do_update(
            constraint="uq_email_threads_user_id_gmail_thread_id",
            set_={**values, "updated_at": func.now()},
        )
        .returning(EmailThread)
        .execution_options(populate_existing=True)
    )
    return session.execute(stmt).scalar_one()


def _same_result(row: Classification, result: ClassificationResult) -> bool:
    return (
        row.label == result.label
        and row.confidence == result.confidence
        and row.method == result.method
        and row.rule_id == result.rule_id
        and row.model_version == result.model_version
        and row.needs_review == result.needs_review
    )


def classifications_of(
    session: Session, user_id: uuid.UUID, thread: EmailThread
) -> list[Classification]:
    """All classification rows of the thread, oldest first."""
    if thread.user_id != user_id:
        raise NotFound("thread")
    stmt = (
        select(Classification)
        .where(Classification.thread_id == thread.id)
        .order_by(Classification.seq)
    )
    return list(session.scalars(stmt))


def classified_message_ids(session: Session, user_id: uuid.UUID, thread: EmailThread) -> set[str]:
    """Gmail ids of the thread's messages that already have a classification row."""
    return {
        row.gmail_message_id
        for row in classifications_of(session, user_id, thread)
        if row.gmail_message_id is not None
    }


def _fill(row: Classification, result: ClassificationResult) -> None:
    row.label = result.label
    row.confidence = result.confidence
    row.method = result.method
    row.rule_id = result.rule_id
    row.model_version = result.model_version
    row.needs_review = result.needs_review


def add_classification(
    session: Session,
    user_id: uuid.UUID,
    thread: EmailThread,
    result: ClassificationResult,
    message_id: str | None = None,
) -> Classification:
    """Store a result. With `message_id` there is one row per message (a re-run replaces its
    values); without, a row is appended unless the latest one already holds the same result."""
    if thread.user_id != user_id:
        raise NotFound("thread")
    if message_id is not None:
        existing = session.scalars(
            select(Classification).where(
                Classification.thread_id == thread.id,
                Classification.gmail_message_id == message_id,
            )
        ).one_or_none()
        if existing is not None:
            _fill(existing, result)
            session.flush()
            return existing
    else:
        latest = session.scalars(
            select(Classification)
            .where(Classification.thread_id == thread.id)
            .order_by(Classification.seq.desc())
            .limit(1)
        ).one_or_none()
        if latest is not None and _same_result(latest, result):
            return latest
    row = Classification(thread_id=thread.id, gmail_message_id=message_id)
    _fill(row, result)
    session.add(row)
    session.flush()
    return row


def delete_all(session: Session, user_id: uuid.UUID) -> int:
    """Delete the user's threads; classifications cascade, applications keep and lose the link."""
    stmt = delete(EmailThread).where(EmailThread.user_id == user_id)
    return cast(CursorResult[Any], session.execute(stmt)).rowcount
