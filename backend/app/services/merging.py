"""Which existing application a new thread belongs to (one card per real application).

Key per user: normalised company plus normalised role, within MERGE_WINDOW of the thread. Merge
when the company matches and the roles match or one side has no role; never across different
roles. Without a company on either side, merge only when exactly one candidate has the same role
and the same sender domain. Pure matching on already-extracted fields; no email text here.
"""

import re
import uuid
from datetime import timedelta

from sqlalchemy.orm import Session

from app.models import Application, EmailThread
from app.repositories import applications as applications_repo
from app.repositories.applications import MergeCandidate
from app.services.extraction import Extracted, is_generic_domain
from app.services.prefilter import is_ats_domain

MERGE_WINDOW = timedelta(days=45)

_COMPANY_SUFFIXES = frozenset(
    {
        "corp",
        "corporation",
        "inc",
        "incorporated",
        "llc",
        "ltd",
        "limited",
        "labs",
        "lab",
        "technologies",
        "technology",
        "co",
        "company",
    }
)
_ROLE_DROPPED = frozenset(
    {
        "intern",
        "interns",
        "internship",
        "internships",
        "the",
        "a",
        "an",
        "position",
        "role",
        "summer",
        "winter",
        "spring",
        "fall",
        "autumn",
    }
)
_YEAR = re.compile(r"^(?:19|20)\d\d$")
_STEMS = {"engineering": "engineer", "engineers": "engineer", "developers": "developer"}


def _tokens(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9 ]", " ", text.casefold().replace("&", " and ")).split()


def normalize_company(company: str | None) -> str:
    tokens = _tokens(company or "")
    while len(tokens) > 1 and tokens[-1] in _COMPANY_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def normalize_role(role: str | None) -> str:
    """Role without season, year and intern/internship wording ('' when nothing is left)."""
    tokens = [_STEMS.get(t, t) for t in _tokens(role or "")]
    return " ".join(t for t in tokens if t not in _ROLE_DROPPED and not _YEAR.match(t))


def _role_compatible(a: str, b: str) -> bool:
    return not a or not b or a == b


def _by_company(candidates: list[MergeCandidate], company: str, role: str) -> list[MergeCandidate]:
    same = [c for c in candidates if normalize_company(c.application.company) == company]
    exact = [c for c in same if role and normalize_role(c.application.role) == role]
    if exact:
        return exact
    return [c for c in same if _role_compatible(role, normalize_role(c.application.role))]


def _identifies_employer(domain: str) -> bool:
    """A sender domain shared by many employers (an ATS, a mail provider) proves nothing."""
    return bool(domain) and not is_ats_domain(domain) and not is_generic_domain(domain)


def _by_role_and_domain(
    candidates: list[MergeCandidate], role: str, domain: str
) -> list[MergeCandidate]:
    if not _identifies_employer(domain):
        return []
    return [
        c
        for c in candidates
        if role
        and normalize_role(c.application.role) == role
        and domain in c.domains
        and not normalize_company(c.application.company)
    ]


def _only(matches: list[MergeCandidate]) -> Application | None:
    return matches[0].application if len(matches) == 1 else None


def pick_target(
    candidates: list[MergeCandidate], extracted: Extracted, domain: str
) -> Application | None:
    """The one candidate this thread belongs to, or None when there is none or it is ambiguous."""
    company, role = normalize_company(extracted.company), normalize_role(extracted.role)
    if company:
        matches = _by_company(candidates, company, role)
        if len(matches) > 1 and not role:
            return None  # same company, several roles, and nothing says which
        if matches:
            return matches[0].application  # several: the oldest card
        return _only(_by_role_and_domain(candidates, role, domain))
    if not _identifies_employer(domain):
        return None
    without_company = [c for c in candidates if role and normalize_role(c.application.role) == role]
    return _only(
        [
            c
            for c in without_company
            if domain in c.domains and not normalize_company(c.application.company)
        ]
    )


def find_merge_target(
    session: Session, user_id: uuid.UUID, thread: EmailThread, extracted: Extracted
) -> Application | None:
    candidates = applications_repo.merge_candidates(session, user_id, thread, MERGE_WINDOW)
    return pick_target(candidates, extracted, thread.from_domain)
