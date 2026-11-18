"""Sequence reads and writes. Every query is scoped by user_id."""

import uuid
from collections.abc import Callable
from collections.abc import Sequence as Seq

from sqlalchemy import select
from sqlalchemy import update as sql_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import InvalidOperation, NotFound
from app.models import Sequence
from app.services.sequences import DEFAULT_STEPS, Step, clean_name, clean_tone, parse_steps


def _dump(steps: list[Step]) -> list[dict[str, object]]:
    return [s.model_dump() for s in steps]


_DEFAULT_INDEX = "uq_sequences_user_id_default"
_MAX_DEFAULT_ATTEMPTS = 3


def _unset_other_defaults(session: Session, user_id: uuid.UUID, keep: uuid.UUID | None) -> None:
    stmt = sql_update(Sequence).where(Sequence.user_id == user_id, Sequence.is_default.is_(True))
    if keep is not None:
        stmt = stmt.where(Sequence.id != keep)
    session.execute(stmt.values(is_default=False))


def _lost_default_race(exc: IntegrityError) -> bool:
    return _DEFAULT_INDEX in str(exc.orig)


def _claim_default(
    session: Session, user_id: uuid.UUID, keep: uuid.UUID | None, write: Callable[[], None]
) -> None:
    """Unset the old default and run `write` in a savepoint; retry when a concurrent writer wins."""
    for attempt in range(_MAX_DEFAULT_ATTEMPTS):
        try:
            with session.begin_nested():
                _unset_other_defaults(session, user_id, keep)
                write()
                session.flush()
            return
        except IntegrityError as exc:
            if not _lost_default_race(exc) or attempt == _MAX_DEFAULT_ATTEMPTS - 1:
                raise


def get(session: Session, user_id: uuid.UUID, sequence_id: uuid.UUID) -> Sequence:
    stmt = select(Sequence).where(Sequence.user_id == user_id, Sequence.id == sequence_id)
    sequence = session.scalars(stmt).one_or_none()
    if sequence is None:
        raise NotFound("sequence")
    return sequence


def list_for_user(session: Session, user_id: uuid.UUID) -> list[Sequence]:
    stmt = select(Sequence).where(Sequence.user_id == user_id).order_by(Sequence.created_at)
    return list(session.scalars(stmt).all())


def create(
    session: Session,
    user_id: uuid.UUID,
    name: str,
    steps: Seq[Step | dict[str, object]],
    tone: str = "short",
    make_default: bool = False,
) -> Sequence:
    """Raises ValueError (name, tone) or pydantic.ValidationError (steps) on bad input."""
    sequence = Sequence(
        user_id=user_id,
        name=clean_name(name),
        steps=_dump(parse_steps(steps)),
        tone=clean_tone(tone),
        is_default=make_default,
    )
    if make_default:
        _claim_default(session, user_id, None, lambda: session.add(sequence))
    else:
        session.add(sequence)
        session.flush()
    return sequence


def update(
    session: Session,
    user_id: uuid.UUID,
    sequence_id: uuid.UUID,
    *,
    name: str | None = None,
    steps: Seq[Step | dict[str, object]] | None = None,
    tone: str | None = None,
    make_default: bool | None = None,
) -> Sequence:
    sequence = get(session, user_id, sequence_id)
    if make_default is False and sequence.is_default:
        raise InvalidOperation("Make another sequence the default instead")
    if steps is not None:
        sequence.steps = _dump(parse_steps(steps))
    if name is not None:
        sequence.name = clean_name(name)
    if tone is not None:
        sequence.tone = clean_tone(tone)
    if make_default is True and not sequence.is_default:
        _claim_default(session, user_id, sequence.id, lambda: setattr(sequence, "is_default", True))
    session.flush()
    return sequence


def get_or_create_default(session: Session, user_id: uuid.UUID) -> Sequence:
    stmt = select(Sequence).where(Sequence.user_id == user_id, Sequence.is_default.is_(True))
    existing = session.scalars(stmt).one_or_none()
    if existing is not None:
        return existing
    sequence = Sequence(
        user_id=user_id,
        name="Default follow-up",
        steps=_dump(list(DEFAULT_STEPS)),
        tone="short",
        is_default=True,
    )
    try:
        with session.begin_nested():
            session.add(sequence)
            session.flush()
    except IntegrityError as exc:
        if not _lost_default_race(exc):
            raise
        return session.scalars(stmt).one()
    return sequence
