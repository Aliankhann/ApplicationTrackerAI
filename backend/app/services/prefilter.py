"""Cheap, pure check for whether an email could be job related. Biased toward keeping.

Never log or return email text: decisions carry only short stable reason identifiers.
"""

import re
import unicodedata
from dataclasses import dataclass
from email.utils import parseaddr

ATS_DOMAINS: tuple[str, ...] = (
    "greenhouse.io",
    "greenhouse-mail.io",
    "lever.co",
    "hire.lever.co",
    "ashbyhq.com",
    "myworkdayjobs.com",
    "workday.com",
    "icims.com",
    "smartrecruiters.com",
    "workable.com",
    "jobvite.com",
    "taleo.net",
    "successfactors.com",
    "bamboohr.com",
    "recruitee.com",
    "hackerrank.com",
    "hackerrankforwork.com",
    "codesignal.com",
    "codility.com",
)

# Extend here (US-41/US-42). Base forms, lowercase, accent-free; _SUFFIX adds plurals and
# inflections. "unfortunately" is deliberately absent: rejections are caught by the others.
JOB_KEYWORDS: tuple[str, ...] = (
    "application",
    "applicant",
    "applied",
    "applying",
    "candidate",
    "candidacy",
    "interview",
    "assessment",
    "coding challenge",
    "coding test",
    "online assessment",
    "take-home",
    "hirevue",
    "phone screen",
    "screening",
    "superday",
    "onsite",
    "on-site",
    "next round",
    "next steps",
    "offer",
    "offer letter",
    "offer of employment",
    "internship",
    "intern",
    "co-op",
    "recruiter",
    "recruiting",
    "recruitment",
    "hiring",
    "hire",
    "hiring team",
    "talent",
    "talent acquisition",
    "position",
    "role",
    "job",
    "career",
    "opening",
    "onboarding",
    "background check",
    "schedule a call",
    "availability",
    "move forward",
    "moving forward",
    "regret to inform",
    "rejection",
    "welcome to the team",
    "thank you for applying",
    "your submission",
    "interest in",
    "resume",
    "cv",
    # French basics
    "entretien",
    "candidature",
    "poste",
    "offre d'emploi",
    "recrutement",
    "stage",
)

# Sender local part or display name words that signal a recruiting sender.
SENDER_KEYWORDS: tuple[str, ...] = (
    "recruit",
    "recruiter",
    "talent",
    "career",
    "job",
    "hr",
    "hiring",
)

# Phrases that contain a keyword but are not job related; removed before matching.
NON_JOB_PHRASES: tuple[str, ...] = ("role model",)

_SUFFIX = r"(?:s|es|ed|d|ing|ers?|ment|ments)?"


def _compile(words: tuple[str, ...], suffix: str = _SUFFIX) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(w).replace(r"\ ", r"\s+") for w in words)
    return re.compile(rf"\b(?:{alternatives}){suffix}\b", re.IGNORECASE)


_KEYWORD_RE = _compile(JOB_KEYWORDS)
_SENDER_RE = _compile(SENDER_KEYWORDS)
_NON_JOB_RE = _compile(NON_JOB_PHRASES)


def _normalize(text: str) -> str:
    """Strip accents so French text and 'r\u00e9sum\u00e9' match the accent-free keywords."""
    if text.isascii():
        return text
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c))


@dataclass(frozen=True)
class EmailMeta:
    from_address: str
    from_name: str
    subject: str
    snippet: str


@dataclass(frozen=True)
class Decision:
    keep: bool
    reason: str


def sender_domain(from_address: str) -> str:
    """Lowercase domain after the last '@', or '' when the address is missing or garbage."""
    _, addr = parseaddr(from_address or "")
    candidate = addr if "@" in addr else (from_address or "")
    if "@" not in candidate:
        return ""
    domain = candidate.rsplit("@", 1)[1].strip().strip("<>").strip().lower().rstrip(".")
    return domain if domain and not any(c.isspace() for c in domain) else ""


def is_ats_domain(domain: str) -> bool:
    """True for an ATS domain or any of its subdomains, never for lookalikes."""
    return any(domain == ats or domain.endswith("." + ats) for ats in ATS_DOMAINS)


def sender_local_part(from_address: str) -> str:
    """Local part of the address, with separators turned into spaces; '' when unknown."""
    _, addr = parseaddr(from_address or "")
    candidate = addr if "@" in addr else (from_address or "")
    if "@" not in candidate:
        return ""
    return re.sub(r"[._+\-]", " ", candidate.rsplit("@", 1)[0])


def has_job_keyword(*texts: str) -> bool:
    return any(_has_keyword(_normalize(t)) for t in texts)


def _has_keyword(text: str) -> bool:
    """One pass; a keyword match is ignored when it starts a non-job phrase."""
    return any(not _NON_JOB_RE.match(text, m.start()) for m in _KEYWORD_RE.finditer(text))


def has_job_sender(email: EmailMeta) -> bool:
    return any(
        _SENDER_RE.search(_normalize(t))
        for t in (sender_local_part(email.from_address), email.from_name)
    )


def prefilter(email: EmailMeta) -> Decision:
    """Keep ATS senders, then anything with a job keyword; drop the rest."""
    if is_ats_domain(sender_domain(email.from_address)):
        return Decision(keep=True, reason="ats_domain")
    if has_job_keyword(email.subject, email.snippet, email.from_name):
        return Decision(keep=True, reason="job_keyword")
    if has_job_sender(email):
        return Decision(keep=True, reason="job_sender")
    return Decision(keep=False, reason="no_signal")
