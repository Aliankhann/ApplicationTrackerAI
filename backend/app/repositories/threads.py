"""Thread metadata and classification history. Every query is scoped by user_id."""

import uuid

from sqlalchemy import func
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


def upsert_thread(
    session: Session,
    user_id: uuid.UUID,
    meta: ThreadMeta,
    subject: str,
    from_domain: str,
    snippet: str,
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


def add_classification(
    session: Session, user_id: uuid.UUID, thread: EmailThread, result: ClassificationResult
) -> Classification:
    if thread.user_id != user_id:
        raise NotFound("thread")
    row = Classification(
        thread_id=thread.id,
        label=result.label,
        confidence=result.confidence,
        method=result.method,
        rule_id=result.rule_id,
        model_version=result.model_version,
        needs_review=result.needs_review,
    )
    session.add(row)
    session.flush()
    return row
