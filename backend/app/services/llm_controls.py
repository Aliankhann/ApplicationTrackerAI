"""Cost and safety controls for the LLM fallback (US-46): kill switch, per-user daily cap, and a
global monthly call budget. Counted in Postgres so every instance shares them. Logs counts only."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.log import get_logger
from app.repositories import llm_usage as usage_repo

logger = get_logger("app.llm_controls")


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int


def _today() -> date:
    return datetime.now(UTC).date()


class LlmControls:
    """Shared for one run; `for_user` binds a session and user for the cap checks."""

    def __init__(
        self, daily_cap: int, monthly_budget: int, today: Callable[[], date] = _today
    ) -> None:
        self._daily_cap = daily_cap
        self._monthly_budget = monthly_budget
        self._today = today
        self._budget_logged = False

    def allow(self, session: Session, user_id: uuid.UUID) -> bool:
        day = self._today()
        if usage_repo.calls_since(session, day.replace(day=1)) >= self._monthly_budget:
            self._log_budget_exceeded()
            return False
        return usage_repo.calls_on(session, user_id, day) < self._daily_cap

    def record(self, session: Session, user_id: uuid.UUID, usage: Usage) -> None:
        usage_repo.record_call(
            session, user_id, self._today(), usage.input_tokens, usage.output_tokens
        )

    def _log_budget_exceeded(self) -> None:
        if not self._budget_logged:
            self._budget_logged = True
            logger.warning("llm.budget_exceeded")
