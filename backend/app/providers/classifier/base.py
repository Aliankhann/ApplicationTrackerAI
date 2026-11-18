"""The interface callers depend on; rules and the LLM fallback both implement it."""

import uuid
from typing import Protocol, runtime_checkable

from sqlalchemy.orm import Session

from app.providers.classifier.types import ClassificationInput, ClassificationResult


class ClassifierProvider(Protocol):
    def classify(self, inp: ClassificationInput) -> ClassificationResult: ...


@runtime_checkable
class UserBoundClassifier(Protocol):
    """A classifier that needs the user (for per-user caps) and a session; sync binds it once."""

    def for_user(self, session: Session, user_id: uuid.UUID) -> ClassifierProvider: ...
