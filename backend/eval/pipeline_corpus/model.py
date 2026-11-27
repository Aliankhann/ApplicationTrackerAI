"""Corpus types. Everything here is invented; nothing is real mail."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Msg:
    from_name: str
    from_address: str
    subject: str
    snippet: str  # what Gmail shows (boilerplate included); may exceed 200, sync truncates
    days_ago: int
    from_user: bool = False
    draft: bool = False
    tail: str = ""  # text after the snippet window, for the "read more" what-if only
    body: str = ""  # plain text as the user would see it; "" means derive it (see body_of)


@dataclass(frozen=True)
class Case:
    id: str
    family: str  # template family, e.g. greenhouse, workday, noise.newsletter
    messages: tuple[Msg, ...]
    kind: str  # "application" | "recruiter" | "noise"
    label: str | None = None  # expected final label of the thread's chosen message
    status: str | None = None  # expected application status (application kind)
    company: str | None = None
    role: str | None = None
    group: str | None = None  # same real application spread over several threads


SNIPPET_CHARS = 200


def gmail_snippet(body: str) -> str:
    """What a Gmail preview shows: the start of the body with whitespace collapsed."""
    return " ".join(body.split())[:SNIPPET_CHARS]
