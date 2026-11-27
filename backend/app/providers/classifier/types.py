"""Shared classifier types. The LLM fallback only ever sees domain, subject and snippet; `body`
is for the rules and is stripped before any LLM call."""

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
    body: str = ""  # cleaned, bounded body text; rules read it, an LLM never sees it


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
