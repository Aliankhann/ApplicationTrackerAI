import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, ValidationError

from app.api.deps import CurrentUser, Db
from app.errors import InvalidOperation, NotFound
from app.models import Sequence
from app.repositories import sequences as repo
from app.services import sequences as service
from app.services import templates
from app.services.sequences import Step

router = APIRouter(prefix="/sequences", tags=["sequences"])

SAMPLE_CONTEXT = {
    "recruiter_first_name": "Alex",
    "role": "Software Engineering Intern",
    "company": "Example Co",
    "applied_date": "March 3",
    "your_name": "Sam Student",
}


class SequenceOut(BaseModel):
    id: uuid.UUID
    name: str
    steps: list[Step]
    tone: str
    is_default: bool


class SequenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    steps: list[dict[str, Any]]
    tone: str = "short"
    make_default: bool = False


class SequencePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    steps: list[dict[str, Any]] | None = None
    tone: str | None = None
    make_default: bool | None = None


class PreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: str
    tone: str = "short"


class PreviewOut(BaseModel):
    text: str


FieldError = dict[str, str]


def _out(sequence: Sequence) -> SequenceOut:
    steps = service.parse_stored_steps(sequence.steps) or []
    return SequenceOut(
        id=sequence.id,
        name=sequence.name,
        steps=steps,
        tone=sequence.tone,
        is_default=sequence.is_default,
    )


def _unprocessable(errors: list[FieldError]) -> HTTPException:
    return HTTPException(status_code=422, detail=errors)


def _normalize(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pasted text may carry \\r\\n; store \\n."""
    out = []
    for step in steps:
        template = step.get("template")
        if isinstance(template, str):
            step = {**step, "template": template.replace("\r\n", "\n").replace("\r", "\n")}
        out.append(step)
    return out


def _pydantic_errors(exc: ValidationError, prefix: str) -> list[FieldError]:
    errors = []
    for err in exc.errors():
        loc = ".".join([prefix, *(str(p) for p in err["loc"])])
        if err["type"] == "value_error":
            message = str(err["ctx"]["error"])
            code = "invalid_template" if loc.endswith("template") else "invalid_value"
            if loc == prefix:
                code = "delays_not_increasing"
        else:
            message, code = err["msg"], err["type"]
        errors.append({"field": loc, "code": code, "message": message})
    return errors


def _check(
    name: str | None, steps: list[dict[str, Any]] | None, tone: str | None
) -> list[FieldError]:
    errors: list[FieldError] = []
    try:
        if name is not None:
            service.clean_name(name)
    except ValueError as exc:
        errors.append({"field": "name", "code": "invalid_name", "message": str(exc)})
    try:
        if tone is not None:
            service.clean_tone(tone)
    except ValueError as exc:
        errors.append({"field": "tone", "code": "invalid_tone", "message": str(exc)})
    try:
        if steps is not None:
            service.parse_steps(steps)
    except ValidationError as exc:
        errors.extend(_pydantic_errors(exc, "steps"))
    return errors


@router.get("", response_model=list[SequenceOut])
def list_sequences(user: CurrentUser, db: Db) -> list[SequenceOut]:
    repo.get_or_create_default(db, user.id)
    db.commit()
    return [_out(s) for s in repo.list_for_user(db, user.id)]


@router.post("", response_model=SequenceOut, status_code=201)
def create_sequence(body: SequenceCreate, user: CurrentUser, db: Db) -> SequenceOut:
    steps = _normalize(body.steps)
    errors = _check(body.name, steps, body.tone)
    if errors:
        raise _unprocessable(errors)
    sequence = repo.create(db, user.id, body.name, steps, body.tone, body.make_default)
    db.commit()
    return _out(sequence)


@router.post("/preview", response_model=PreviewOut)
def preview(body: PreviewBody, user: CurrentUser) -> PreviewOut:
    """Render a template with sample data; writes nothing and uses no real recipient data."""
    template = body.template.replace("\r\n", "\n").replace("\r", "\n")
    try:
        text = templates.render(template, SAMPLE_CONTEXT, tone=body.tone)  # type: ignore[arg-type]
    except templates.TemplateError as exc:
        field = "tone" if "tone" in str(exc).lower() else "template"
        raise _unprocessable(
            [{"field": field, "code": f"invalid_{field}", "message": str(exc)}]
        ) from None
    return PreviewOut(text=text)


@router.patch("/{sequence_id}", response_model=SequenceOut)
def patch_sequence(
    sequence_id: uuid.UUID, body: SequencePatch, user: CurrentUser, db: Db
) -> SequenceOut:
    steps = _normalize(body.steps) if body.steps is not None else None
    errors = _check(body.name, steps, body.tone)
    if errors:
        raise _unprocessable(errors)
    try:
        sequence = repo.update(
            db,
            user.id,
            sequence_id,
            name=body.name,
            steps=steps,
            tone=body.tone,
            make_default=body.make_default,
        )
    except NotFound:
        db.rollback()
        raise HTTPException(status_code=404, detail="not_found") from None
    except InvalidOperation as exc:
        db.rollback()
        raise _unprocessable(
            [{"field": "make_default", "code": "invalid_operation", "message": str(exc)}]
        ) from None
    db.commit()
    return _out(sequence)
