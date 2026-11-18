"""LLM usage counters: per user per day, plus one global monthly total for the budget."""

import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import LlmUsage


def calls_on(session: Session, user_id: uuid.UUID, day: date) -> int:
    stmt = select(LlmUsage.calls).where(LlmUsage.user_id == user_id, LlmUsage.day == day)
    return session.scalar(stmt) or 0


def calls_since(session: Session, first_day: date) -> int:
    """Global total across all users (aggregate only, no per-user data leaves this function)."""
    stmt = select(func.coalesce(func.sum(LlmUsage.calls), 0)).where(LlmUsage.day >= first_day)
    return int(session.scalar(stmt) or 0)


def record_call(
    session: Session, user_id: uuid.UUID, day: date, input_tokens: int, output_tokens: int
) -> None:
    stmt = insert(LlmUsage).values(
        id=uuid.uuid4(),
        user_id=user_id,
        day=day,
        calls=1,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_llm_usage_user_id_day",
        set_={
            "calls": LlmUsage.calls + 1,
            "input_tokens": LlmUsage.input_tokens + input_tokens,
            "output_tokens": LlmUsage.output_tokens + output_tokens,
        },
    )
    session.execute(stmt)
