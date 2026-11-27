"""Rules first; the LLM only when the rules are undecided, within the cost controls (US-45/46).

The LLM stage sits behind the existing cache, so an identical email never costs twice. Any LLM
failure falls back to the rules result. Logs event names, counts and error codes only.
"""

import uuid
from dataclasses import dataclass, replace

from sqlalchemy.orm import Session

from app.log import get_logger
from app.providers.classifier.base import ClassifierProvider
from app.providers.classifier.cache import CachingProvider
from app.providers.classifier.claude import ClaudeProvider, LlmError
from app.providers.classifier.types import ClassificationInput, ClassificationResult
from app.services.llm_controls import LlmControls

logger = get_logger("app.classifier.router")


@dataclass
class RouterStats:
    total: int = 0
    llm_calls: int = 0

    @property
    def llm_share(self) -> float:
        return self.llm_calls / self.total if self.total else 0.0


class RoutedClassifier:
    """Shared for one run. With controls, `classify` is rules-only and `for_user` adds the capped
    LLM stage. Without controls (offline eval only) `classify` may call the LLM."""

    def __init__(
        self, rules: ClassifierProvider, llm: ClaudeProvider, controls: LlmControls | None
    ) -> None:
        self._rules = rules
        self._llm = llm
        self._cached = CachingProvider(llm)
        self._controls = controls
        self.stats = RouterStats()

    def classify(self, inp: ClassificationInput) -> ClassificationResult:
        return self.route(inp, None, None)

    def for_user(self, session: Session, user_id: uuid.UUID) -> ClassifierProvider:
        return _UserRouter(self, session, user_id)

    def route(
        self, inp: ClassificationInput, session: Session | None, user_id: uuid.UUID | None
    ) -> ClassificationResult:
        self.stats.total += 1
        result = self._rules.classify(inp)
        if result.label is not None:
            return result
        if self._controls is not None and not self._allowed(session, user_id):
            return result
        return self._ask_llm(inp, result, session, user_id)

    def _allowed(self, session: Session | None, user_id: uuid.UUID | None) -> bool:
        if self._controls is None:
            return True
        return (
            session is not None and user_id is not None and self._controls.allow(session, user_id)
        )

    def _ask_llm(
        self,
        inp: ClassificationInput,
        fallback: ClassificationResult,
        session: Session | None,
        user_id: uuid.UUID | None,
    ) -> ClassificationResult:
        try:
            answer = self._cached.classify(replace(inp, body=""))  # the body never leaves rules
        except LlmError as exc:
            self._record_usage(session, user_id)
            logger.warning("llm.call_failed", extra={"error_code": exc.code})
            return fallback
        self._record_usage(session, user_id)
        return answer if answer.label is not None else fallback

    def _record_usage(self, session: Session | None, user_id: uuid.UUID | None) -> None:
        usage = self._llm.take_usage()
        if usage is None:  # cache hit: no API call, no cost
            return
        self.stats.llm_calls += 1
        if self._controls is not None and session is not None and user_id is not None:
            self._controls.record(session, user_id, usage)


class _UserRouter:
    def __init__(self, router: RoutedClassifier, session: Session, user_id: uuid.UUID) -> None:
        self._router = router
        self._session = session
        self._user_id = user_id

    def classify(self, inp: ClassificationInput) -> ClassificationResult:
        return self._router.route(inp, self._session, self._user_id)
