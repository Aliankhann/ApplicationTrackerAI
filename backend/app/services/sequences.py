"""Follow-up sequence step schema and validation."""

from collections.abc import Sequence
from itertools import pairwise
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from app.services.templates import TemplateError, strip_unsafe, validate_template, validate_tone

MAX_STEPS = 5
MAX_NAME_LENGTH = 80


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delay_days: Annotated[int, Field(ge=1, le=60)]
    template: Annotated[str, Field(min_length=1, max_length=2000)]
    max_attempts: Annotated[int, Field(ge=1, le=3)] = 1

    @field_validator("template")
    @classmethod
    def _template_is_safe(cls, value: str) -> str:
        try:
            validate_template(value)
        except TemplateError as exc:
            raise ValueError(str(exc)) from exc
        return value


def _check_delays(steps: list[Step]) -> list[Step]:
    delays = [s.delay_days for s in steps]
    if any(b <= a for a, b in pairwise(delays)):
        raise ValueError("Step delays must be strictly increasing (days since the application)")
    return steps


Steps = Annotated[
    list[Step], Field(min_length=1, max_length=MAX_STEPS), AfterValidator(_check_delays)
]
_STEPS_ADAPTER: TypeAdapter[list[Step]] = TypeAdapter(Steps)


def parse_stored_steps(raw: object) -> list[Step] | None:
    """Steps from stored JSON, or None when they no longer validate (never raises)."""
    try:
        return _STEPS_ADAPTER.validate_python(raw)
    except ValidationError:
        return None


def clean_name(name: str) -> str:
    cleaned = " ".join(strip_unsafe(name.replace("\t", " ")).split())
    if not 1 <= len(cleaned) <= MAX_NAME_LENGTH:
        raise ValueError(f"Name must be 1 to {MAX_NAME_LENGTH} characters")
    return cleaned


def clean_tone(tone: str) -> str:
    try:
        validate_tone(tone)
    except TemplateError as exc:
        raise ValueError(str(exc)) from exc
    return tone


def parse_steps(raw: Sequence[Step | dict[str, object]]) -> list[Step]:
    """Validate raw step data; raises pydantic.ValidationError with clear messages."""
    return _STEPS_ADAPTER.validate_python(raw)


DEFAULT_STEPS = [
    Step(
        delay_days=7,
        template=(
            "I applied for the {role} position at {company} on {applied_date} and wanted to "
            "follow up. I'm still very interested and happy to share anything else you need."
        ),
    ),
    Step(
        delay_days=14,
        template=(
            "I'm checking in once more about the {role} role at {company}. If the position "
            "has been filled, I'd appreciate hearing so. Thank you for your time."
        ),
    ),
]
