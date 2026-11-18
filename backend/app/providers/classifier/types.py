"""Shared classifier types. Input carries only what an LLM fallback may ever see."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class Label(StrEnum):
    CONFIRMATION = "confirmation"
    ONLINE_ASSESSMENT = "online_assessment"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTION = "rejection"
    RECRUITER_MESSAGE = "recruiter_message"
    IRRELEVANT = "irrelevant"


@dataclass(frozen=True)
class ClassificationInput:
    from_domain: str
    subject: str
    snippet: str


@dataclass(frozen=True)
class ClassificationResult:
    """`label=None` means undecided."""

    label: Label | None
    confidence: float
    method: Literal["rules", "llm"]
    rule_id: str | None
    needs_review: bool
    model_version: str | None = None
    company: str | None = None  # LLM suggestion, already cleaned; rules extraction wins
    role: str | None = None
