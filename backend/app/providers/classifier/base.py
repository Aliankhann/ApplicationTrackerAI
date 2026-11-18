"""The interface callers depend on; rules and the LLM fallback both implement it."""

from typing import Protocol

from app.providers.classifier.types import ClassificationInput, ClassificationResult


class ClassifierProvider(Protocol):
    def classify(self, inp: ClassificationInput) -> ClassificationResult: ...
