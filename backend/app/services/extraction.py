"""Pure company and role extraction from sender and subject. Returns None rather than guessing.

Never logs or returns more than the extracted company and role: no email text leaves this module.
"""

import re
from dataclasses import dataclass
from email.utils import parseaddr

from app.services.prefilter import is_ats_domain, sender_domain
from app.text import normalize_text

MAX_COMPANY = 80
MAX_ROLE = 120
MAX_ROLE_WORDS = 9
MAX_COMPANY_WORDS = 6
MAX_NAME_INPUT = 150
MAX_SUBJECT_INPUT = 300
MAX_SNIPPET_INPUT = 500
MAX_BODY_INPUT = 4000
SIGNOFF_LINES = 8  # the sign-off sits in the last lines of the cleaned body

SOURCE_DISPLAY_NAME = "display_name"
SOURCE_SUBJECT = "subject"
SOURCE_DOMAIN = "domain"
SOURCE_SNIPPET = "snippet"
SOURCE_BODY = "body"
SOURCE_LLM = "llm"

VENDOR_NAMES: frozenset[str] = frozenset(
    {
        "greenhouse",
        "lever",
        "workday",
        "myworkdayjobs",
        "ashby",
        "ashbyhq",
        "icims",
        "smartrecruiters",
        "smart recruiters",
        "workable",
        "jobvite",
        "taleo",
        "successfactors",
        "sap successfactors",
        "bamboohr",
        "recruitee",
        "hackerrank",
        "codesignal",
        "codility",
        "hirevue",
        "zoom",
        "calendly",
        "goodtime",
        "modernloop",
        "linkedin",
        "indeed",
        "glassdoor",
        "ziprecruiter",
        "handshake",
        "joinhandshake",
        "sendgrid",
        "mailchimp",
        "mailgun",
        "amazonses",
        "salesforce",
        "hubspot",
    }
)
GENERIC_WORDS: frozenset[str] = frozenset(
    {
        "team",
        "no reply",
        "noreply",
        "do not reply",
        "notification",
        "notifications",
        "careers",
        "career",
        "jobs",
        "job",
        "recruiting",
        "recruitment",
        "recruiter",
        "hr",
        "hiring",
        "talent",
        "support",
        "admin",
        "info",
        "mail",
        "email",
        "alerts",
        "hello",
        "application",
        "applications",
        "www",
        "wd",
        "hire",
        "boards",
        "embed",
        "newsletter",
        "news",
        "updates",
        "digest",
        "events",
        "marketing",
        "offers",
        "mailer",
        "notify",
    }
)
_DENY_WORDS = (
    "application|applications|applying|applied|thank|thanks|update|interview|assessment|offer|"
    "invitation|your|re|fwd|next|reminder|action|required|important|urgent|congratulations|"
    "welcome|new|confirmation|received|status|candidate|hello|hi|dear|recruiter"
)
_DENY_RE = re.compile(rf"\b(?:{_DENY_WORDS})\b", re.IGNORECASE)
_COMPANY_DENY_RE = re.compile(
    r"\b(?:program|position|role|opening|posting|internship|on behalf of|representing)\b",
    re.IGNORECASE,
)

_GENERIC_PROVIDER_LABELS: frozenset[str] = frozenset(
    {
        "gmail",
        "googlemail",
        "outlook",
        "hotmail",
        "yahoo",
        "icloud",
        "me",
        "proton",
        "protonmail",
        "pm",
        "live",
        "aol",
        "gmx",
        "mail",
        "msn",
        "yandex",
    }
)
_SUFFIXES = frozenset(
    {"corp", "corporation", "inc", "incorporated", "llc", "ltd", "limited", "co", "company"}
)
_SECOND_LEVEL = frozenset({"co", "com", "org", "net", "ac", "gov", "edu", "ne", "or"})

_JOB_NOUNS = (
    "intern|internship|engineer|developer|analyst|scientist|designer|manager|associate|co-op|"
    "researcher|consultant|specialist|coordinator|representative|technician|architect"
)
_NOUN_RE = re.compile(rf"\b(?:{_JOB_NOUNS})s?\b", re.IGNORECASE)

_DASH_CHARS = chr(0x2013) + chr(0x2014)
_DASHES = rf"\-{_DASH_CHARS}"
_QUOTES = "".join(map(chr, (0x201C, 0x201D, 0x2018, 0x2019)))
_NOISE = (
    r"hiring\s+team|recruiting\s+team|recruitment\s+team|talent\s+acquisition(?:\s+team)?|"
    r"talent\s+team|university\s+recruiting|campus\s+recruiting|early\s+careers|talent|"
    r"recruiting|recruitment|careers?|jobs?|hr|human\s+resources|people\s+team|"
    r"people\s+ops|people|hiring|recrutement|ressources\s+humaines|carrieres|notifications?|"
    r"no[\s-]?reply|noreply|do\s+not\s+reply|team|support|newsletter|news|updates?|digest|"
    r"events?|marketing|offers|info|alerts?|mailer|rewards|billing|invoices?|payments?|"
    r"accounts?|deals|promotions?|weekly|daily|monthly|community|store|shop"
)
_TRAILING_NOISE_RE = re.compile(rf"[\s,|{_DASHES}:@.]*\b(?:{_NOISE})$", re.IGNORECASE)
_VIA_RE = re.compile(r"\s*[(\[]?\s*\bvia\s+(?P<v>[\w .-]{1,40}?)[)\]]?$", re.IGNORECASE)
_AT_PREFIX_RE = re.compile(
    r"^(?:.{0,60}?\b(?:careers?|jobs?|recruiting|recruitment|talent|hiring|recruiter|hr)"
    r"(?:\s+team)?\s+(?:at|@)\s+|.{0,60}?\s@\s*)(?P<c>.+)$",
    re.IGNORECASE,
)
_BEHALF_RE = re.compile(
    r"^.{1,60}?\s+(?:on behalf of|representing|for)\s+(?P<c>.{1,60})$", re.IGNORECASE
)
_CONNECTIVE_RE = re.compile(r"\b(?:on behalf of|via|from|for|representing|at)\b", re.IGNORECASE)
_ORG_WORDS = frozenset(
    [
        "inc",
        "llc",
        "ltd",
        "co",
        "corp",
        "corporation",
        "company",
        "labs",
        "lab",
        "group",
        "technologies",
        "technology",
        "systems",
        "ai",
        "bank",
        "capital",
        "health",
        "robotics",
        "works",
        "studio",
        "studios",
        "foods",
        "logistics",
        "analytics",
        "biotech",
        "software",
        "solutions",
        "partners",
        "ventures",
        "media",
        "energy",
        "networks",
        "design",
        "digital",
        "financial",
        "industries",
        "consulting",
        "holdings",
        "pharma",
        "motors",
        "airlines",
        "university",
        "institute",
        "agency",
        "associates",
    ]
)

_REQ_RES = (
    re.compile(
        r"\(\s*(?:req(?:uisition)?\.?\s*#?\s*[\w-]+|[A-Za-z]{1,4}-?\d[\w-]*|\d{5,})\s*\)",
        re.IGNORECASE,
    ),
    re.compile(rf"[{_DASHES},]?\s*\breq(?:uisition)?\.?\s*#?\s*[\w-]*\d[\w-]*", re.IGNORECASE),
    re.compile(r"#\s*\d+"),
    re.compile(r"\b(?:JR|REQ|R)-?\d{3,}(?:-\d+)*\b"),
    re.compile(r"\bJR-\d{4}-\d+\b"),
)
_SEASON = r"(?:summer|winter|spring|fall|autumn|20\d\d)"
_SEASON_PREFIX_RE = re.compile(rf"^(?:{_SEASON}\s+){{1,2}}", re.IGNORECASE)
_SEASON_RE = re.compile(rf"\b{_SEASON}\b", re.IGNORECASE)
_TRAILING_PAREN_RE = re.compile(r"\s*\(([^()]{1,40})\)$")
_ROLE_TRAILING_RE = re.compile(
    r"\s+(?:position|role|application|opening|assessment|interview|invitation|job|opportunity"
    r"|coding\s+test|test|screening"
    r"|and|or|at|with|for|to|the|a|an|as|in|on|of)$",
    re.IGNORECASE,
)
_ROLE_PREFIX_RE = re.compile(
    r"^(?:(?:thank you|thanks) for applying\s+(?:to|for)|your application\s+(?:to|for)|"
    r"(?:thank you for your |thanks for your )?interest in|"
    r"application for|applying\s+(?:to|for)|re:|fwd?:)\s*(?:the\s+|an?\s+)?",
    re.IGNORECASE,
)
_FIELD_WORDS = frozenset(
    [
        "data",
        "software",
        "machine",
        "engineering",
        "research",
        "marketing",
        "finance",
        "product",
        "design",
        "analytics",
        "security",
        "cloud",
        "hardware",
        "operations",
        "business",
        "ai",
        "ml",
    ]
)

_CONNECTIVES = frozenset({"and", "of", "the", "for", "in", "&", "/", "-", "to"})
_SEP_RE = re.compile(rf"\s+[|{_DASHES}]\s+|\s*\|\s*|:\s+")
_SEP_CAPTURE_RE = re.compile(rf"(\s+[|{_DASHES}]\s+|\s*\|\s*|:\s+)")
_APP_RE = re.compile(
    r"application|applying|thank|interview|assessment|next steps|update|offer|received|"
    r"confirmation|invitation",
    re.IGNORECASE,
)

# All spans are bounded so that matching stays linear-ish on adversarial input.
_COMP_CHAR = rf"(?:[^.\n|,;:!?()\[\]{_DASH_CHARS}]|\.(?!\s+(?-i:[A-Z])))"
_COMP = rf"(?P<c>[^\s.|,;:!?()\[\]{_DASH_CHARS}]{_COMP_CHAR}{{0,79}}?)"
_COMP_END = (
    rf"(?=\s+(?:has|was|is|have|will|for|and\s+(?:for|we|our|i|will))\s|\s+[{_DASHES}|]\s"
    r"|\s*[,;:!?|()\[\]]|\.?\s*$|\.?[ \t]*\n|\.\s)"
)
_COMP_END_TO = r"(?=\s+(?:to|for|has|was|is|will|and)\s|\s*[,;:!?|()\[\]]|\.?\s*$|\.?[ \t]*\n|\.\s)"
# (pattern, needs_at): with needs_at the match only counts when the capture is 'role at X'.
_COMPANY_PATTERNS = (
    (re.compile(rf"\b(?:application|applying)\s+(?:to|at|with)\s+{_COMP}{_COMP_END}", re.I), False),
    (re.compile(rf"\b(?:application|applying)\s+for\s+{_COMP}{_COMP_END}", re.I), True),
    (re.compile(rf"\binterest in\s+{_COMP}{_COMP_END}", re.I), False),
    (re.compile(rf"\bwelcome to\s+{_COMP}{_COMP_END}", re.I), False),
    (re.compile(rf"\bupdate from\s+{_COMP}{_COMP_END}", re.I), False),
    (
        re.compile(
            rf"\b(?:{_JOB_NOUNS})s?(?:\s*\([^)]{{0,60}}\))?\s+(?:at|@)\s+{_COMP}{_COMP_END}", re.I
        ),
        False,
    ),
    (re.compile(rf"\bapplication\s+(?:was\s+)?sent\s+to\s+{_COMP}{_COMP_END}", re.I), False),
    (re.compile(rf"\bapplied\s+for\s+{_COMP}{_COMP_END}", re.I), True),
    (re.compile(rf"\bapplied\s+to\s+{_COMP}{_COMP_END}", re.I), False),
    (
        re.compile(
            rf"\b(?:role|position|opening|job|internship|opportunity|career|careers|team)\s+"
            rf"(?:at|with)\s+{_COMP}{_COMP_END}",
            re.I,
        ),
        False,
    ),
    (re.compile(rf"\bon\s+behalf\s+of\s+{_COMP}{_COMP_END}", re.I), False),
    (re.compile(rf"\binvited\s+by\s+{_COMP}{_COMP_END_TO}", re.I), False),
    (
        re.compile(
            r"(?:^|[,.:;!\n]\s*)(?P<c>(?-i:[A-Z0-9])[^,.:;!?\n]{1,60}?)\s+(?:has\s+)?invited\s+you\b",
            re.I,
        ),
        False,
    ),
    (
        re.compile(
            rf"\b(?:this is|i'?m|i am|my name is)\s+(?-i:[A-Z])[a-z]+(?:\s+(?-i:[A-Z])[a-z]+)?\s+"
            rf"(?:from|at|with)\s+{_COMP}{_COMP_END}",
            re.I,
        ),
        False,
    ),
)
_MODIFIERS = (
    r"(?:(?:final|first|second|technical|onsite|virtual|video|phone|panel|round|1st|2nd|3rd|"
    r"intro|introductory)\s+){0,3}"
)
# Only for sender vendors (calendar, scheduling and assessment tools), where the company is
# named in the invitation text instead of the sender.
_VENDOR_COMPANY_PATTERNS = (
    re.compile(
        rf"\b(?:invitation|updated invitation|topic)\s*:\s*{_COMP}\s+{_MODIFIERS}"
        r"(?:interview|screen)\b",
        re.I,
    ),
    re.compile(rf"\binterview\s+with\s+{_COMP}{_COMP_END}", re.I),
    re.compile(rf"\bwith\s+[^|,;:!?\n]{{2,40}}?\s+[{_DASHES}]\s+{_COMP}\s*$", re.I),
)
_AT_COMPANY_RE = re.compile(r"\s(?:at|@)\s+(?!.*\s(?:at|@)\s)(.+)$", re.IGNORECASE)

_ROLE = r"(?P<r>[^|;:!?,][^|;:!?,]{0,119}?)"
_ROLE_END = (
    rf"(?=\s+(?:at|with|has|was|is|have|will|@)\s|\s+[{_DASHES}|]\s|\s*[,;:!?|]"
    r"|\.\s*$|\.\s+(?:we|your|thank|thanks|please|you|the|this|our)\b|\s*$|[ \t]*\n)"
)
_STOP_WORDS = (
    r"to|for|at|with|that|you|your|our|we|is|was|has|have|will|this|these|time|"
    r"application|applying|applied"
)
_TITLE_WORDS = rf"(?:(?!(?:{_STOP_WORDS})\b)[\w&/+.'-]+\s+){{0,6}}?"
_ROLE_LINE = re.compile(
    r"(?im)^[ \t]*(?:job[ \t]*title|position(?:[ \t]+(?:applied[ \t]+for|title))?|role|job)"
    r"[ \t]*:[ \t]*(?P<r>[^\n]{3,120}?)[ \t]*$"
)
_ROLE_PATTERNS = (
    re.compile(rf"\bposition of\s+(?:the\s+|an?\s+)?{_ROLE}{_ROLE_END}", re.I),
    re.compile(rf"\b(?:assessment|test|challenge)\s*:\s*{_ROLE}{_ROLE_END}", re.I),
    re.compile(
        rf"\b(?:the|an?)\s+(?P<r>{_TITLE_WORDS}[\w&/+.'-]+)\s+(?:role|position|opening|job|opportunity)\b",
        re.I,
    ),
    re.compile(rf"\bas\s+(?:an?\s+)(?P<r>{_TITLE_WORDS}[\w&/+.'-]+)(?=\s*[.,;!?\n]|\s*$)", re.I),
    re.compile(rf"\bfor the\s+{_ROLE}\s+(?:position|role)\b", re.I),
    re.compile(
        rf"\b(?:application|assessment|interview) for\s+(?:the\s+|an?\s+)?{_ROLE}{_ROLE_END}", re.I
    ),
    re.compile(rf"\bapplying (?:to|for)\s+(?:the\s+|an?\s+)?{_ROLE}{_ROLE_END}", re.I),
    re.compile(r"\byour\s+(?P<r>[^|;:!?,]{1,80}?)\s+application\b", re.I),
)
_AT_SPLIT_RE = re.compile(r"^(?P<r>.{1,120}?)\s+(?:at|@)\s+\S", re.IGNORECASE)

_TENANT_DOMAIN_RES = (
    re.compile(r"^(?P<t>[a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com$"),
    re.compile(r"^(?P<t>[a-z0-9-]+)\.(?:jobs|hire)\.lever\.co$"),
)
_TENANT_LINK_RE = re.compile(r"\b(?P<t>[a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com\b", re.IGNORECASE)
_TENANT_URL_RE = re.compile(
    r"\b(?:jobs|hire|boards|job-boards)\.(?:lever\.co|greenhouse\.io|ashbyhq\.com)/"
    r"(?P<t>[a-z0-9-]+)",
    re.IGNORECASE,
)
_VENDOR_PREFIXES = (*(n.replace(" ", "") for n in VENDOR_NAMES), "myworkday")


@dataclass(frozen=True)
class Extracted:
    company: str | None
    role: str | None
    company_source: str | None
    role_source: str | None


@dataclass(frozen=True)
class _Folded:
    """Accent-free text for matching, with a map back to the original characters."""

    text: str
    index: tuple[int, ...]
    original: str

    @classmethod
    def of(cls, original: str) -> "_Folded":
        chars: list[str] = []
        index: list[int] = []
        for i, ch in enumerate(original):
            for out in normalize_text(ch):
                chars.append(out)
                index.append(i)
        return cls("".join(chars), tuple(index), original)

    def group(self, match: re.Match[str], name: str) -> str:
        start, end = match.start(name), match.end(name)
        if start == end:
            return ""
        return self.original[self.index[start] : self.index[end - 1] + 1]


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _trim(text: str) -> str:
    text = _collapse(text).strip(" \t\"'`" + _QUOTES + ",;:|-" + _DASH_CHARS + "_")
    if text.endswith(".") and not re.search(r"\b\w\.$", text):
        text = text[:-1].rstrip()
    return text


def _key(text: str) -> str:
    return _collapse(re.sub(r"[^a-z0-9 ]", " ", normalize_text(text).lower()))


def _has_noun(text: str) -> bool:
    return _NOUN_RE.search(normalize_text(text)) is not None


def _is_vendor(text: str) -> bool:
    """Vendor, ATS, job-board or mail-service names and lookalikes (prefix match)."""
    squashed = _key(text).replace(" ", "")
    return squashed.startswith(_VENDOR_PREFIXES)


_TRAILING_CONNECTIVE_RE = re.compile(
    r"\s+(?:and|or|&|the|a|an|for|to|of|in|at|with|as|on|we|our)$", re.IGNORECASE
)


def _valid_company(name: str) -> str | None:
    name = _trim(name)
    while _TRAILING_CONNECTIVE_RE.search(name):
        name = _trim(_TRAILING_CONNECTIVE_RE.sub("", name))
    key = _key(name)
    if len(name) < 2 or len(name) > MAX_COMPANY or not key or key.isdigit():
        return None
    if len(name) <= 3 and name.islower():
        return None  # a stray lowercase fragment ('th'), not a name
    if key in GENERIC_WORDS or key.startswith("the ") or _is_vendor(name):
        return None
    if len(name.split()) > MAX_COMPANY_WORDS or _has_noun(name):
        return None
    if _DENY_RE.search(key) or _COMPANY_DENY_RE.search(key):
        return None
    return name


def _looks_like_person(name: str) -> bool:
    """2-3 capitalised plain tokens with no organisation word, e.g. 'Priya Natarajan'."""
    tokens = normalize_text(name).split()
    if not 2 <= len(tokens) <= 3 or any(t.lower().strip(".") in _ORG_WORDS for t in tokens):
        return False
    return all(re.fullmatch(r"[A-Z][A-Za-z'.-]*", t) for t in tokens)


def _strip_via(text: str) -> str | None:
    """Drop 'via <vendor>'; any other 'via' means a third party, so give up."""
    match = _VIA_RE.search(text)
    if not match:
        return text
    return text[: match.start()] if _is_vendor(match.group("v")) else None


def _display_company(name: str, domain: str, trusted: bool = False) -> str | None:
    """Company named by a display name; third-party senders are rejected, and so are names that
    look like a person unless the sender is `trusted` (an ATS, which names the employer)."""
    text = _collapse(name.strip("\"'` "))
    at_match = _AT_PREFIX_RE.match(text)
    if at_match:
        text = at_match.group("c")
    behalf = _BEHALF_RE.match(text)
    if behalf:
        text = behalf.group("c")
        if not _consistent(text, domain):
            return None
    stripped = _strip_via(text)
    if stripped is None:
        return None
    text = stripped
    previous = None
    while previous != text:
        previous = text
        text = _TRAILING_NOISE_RE.sub("", text)
    if _CONNECTIVE_RE.search(text):
        return None
    company = _valid_company(text)
    if company and _looks_like_person(company) and not trusted and not _consistent(company, domain):
        return None
    return company


def _title(label: str) -> str | None:
    return _valid_company(label.replace("-", " ").title())


def _registrable_label(domain: str) -> tuple[str, bool] | None:
    """Main label of the registrable domain, and whether it is a generic or academic domain."""
    labels = domain.split(".")
    if len(labels) < 2 or not all(labels):
        return None
    tld, second = labels[-1], labels[-2]
    if len(tld) == 2 and second in _SECOND_LEVEL and len(labels) >= 3:
        label = labels[-3]
        academic = second in {"ac", "edu"}
    else:
        label = second
        academic = tld in {"edu", "ac"} or second in {"ac", "edu"}
    return label, academic or label in _GENERIC_PROVIDER_LABELS


def is_generic_domain(domain: str) -> bool:
    """A mail provider or academic domain, or one that is not a registrable name at all."""
    registrable = _registrable_label(domain)
    return registrable is None or registrable[1]


def _domain_company(domain: str) -> str | None:
    """Lowest-confidence source: never for generic, academic or vendor domains."""
    registrable = _registrable_label(domain)
    if registrable is None or registrable[1] or _is_vendor(registrable[0]):
        return None
    return _title(registrable[0])


def _tenant_company(domain: str, local: str, text: str) -> str | None:
    """Employer named by an ATS: the tenant subdomain, the Workday sender (acme@myworkday.com), or
    a careers link in the text (acme.wd5.myworkdayjobs.com, jobs.lever.co/acme)."""
    for pattern in _TENANT_DOMAIN_RES:
        match = pattern.match(domain)
        if match:
            return _title(match.group("t"))
    if domain == "myworkday.com" or domain.endswith(".myworkday.com"):
        tenant = _title(local) if re.fullmatch(r"[a-z0-9-]+", local) else None
        if tenant:
            return tenant
    link = _TENANT_LINK_RE.search(text)
    if link:
        return _title(link.group("t").lower())
    url = _TENANT_URL_RE.search(text)
    return _title(url.group("t").lower()) if url else None


def _consistent(company: str, domain: str) -> bool:
    registrable = _registrable_label(domain) if domain else None
    if registrable is None:
        return False
    name, label = _key(company).replace(" ", ""), registrable[0].replace("-", "")
    return len(name) >= 3 and len(label) >= 3 and (name in label or label in name)


def _company_from_text(text: str) -> str | None:
    folded = _Folded.of(text)
    for pattern, needs_at in _COMPANY_PATTERNS:
        match = pattern.search(folded.text)
        if not match:
            continue
        candidate = folded.group(match, "c")
        at = _AT_COMPANY_RE.search(candidate)
        if needs_at and not at:
            continue
        found = _valid_company(at.group(1) if at else candidate)
        if found:
            return found
    return None


_CLOSER_RE = re.compile(
    r"^(?:best(?:\s+regards|\s+wishes|\s+of\s+luck)?|sincerely(?:\s+yours)?|thanks(?:\s+again)?|"
    r"thank\s+you|(?:warm|kind|warmest|many)\s+regards|regards|cheers|yours\s+(?:sincerely|truly)|"
    r"wishing\s+you\s+(?:all\s+)?the\s+best)[,.!]?$",
    re.IGNORECASE,
)
_ORG_LINE_RE = re.compile(
    r"^(?P<the>the\s+)?(?P<c>[^,\n]{2,60}?)\s+(?:(?:university|campus|early\s+careers?|college|student|"
    r"talent|people)\s+)*(?:recruiting|recruitment|talent\s+acquisition|talent|hiring|careers?|"
    r"human\s+resources|hr|people(?:\s+ops)?|early\s+careers)(?P<team>\s+team)?\.?$",
    re.IGNORECASE,
)


def _signoff_company(body: str) -> str | None:
    """Company named by the sign-off: 'Best regards, The Acme Talent Acquisition Team'."""
    lines = [ln.strip() for ln in body.split("\n") if ln.strip()][-SIGNOFF_LINES:]
    for i, line in enumerate(lines):
        match = _ORG_LINE_RE.match(_Folded.of(line).text)
        if not match:
            continue
        closed = any(_CLOSER_RE.match(prev) for prev in lines[max(0, i - 3) : i])
        if not (closed or (match.group("the") and match.group("team"))):
            continue
        company = _valid_company(_Folded.of(line).group(match, "c"))
        if company:
            return company
    return None


_LOCATION = (
    r"(?-i:[A-Z][A-Za-z.]+(?:\s[A-Z][A-Za-z.]+)*,\s*[A-Z]{2})\b|Remote\b|Hybrid\b|On-?site\b"
)
_JOB_CARD_RE = re.compile(
    rf"(?:^|[.\n]\s*)(?P<r>[^.\n|;:!?]{{3,80}}?)\s*(?:\.\s+|\n\s*|\s[{_DASHES}·]\s+)"
    rf"(?P<c>[^.\n|,;:!?·{_DASH_CHARS}-]{{2,60}}?)\s+[·{_DASHES}]\s+(?:{_LOCATION})",
    re.IGNORECASE,
)


def _job_card(text: str) -> tuple[str | None, str | None]:
    """'Support Engineer Intern - Soylent - Austin, TX' (board confirmations): role, company."""
    folded = _Folded.of(text)
    for match in _JOB_CARD_RE.finditer(folded.text):
        role, company = (
            _valid_role(folded.group(match, "r")),
            _valid_company(folded.group(match, "c")),
        )
        if role and company:
            return role, company
    return None, None


def _company_from_vendor_text(text: str) -> str | None:
    folded = _Folded.of(text)
    for pattern in _VENDOR_COMPANY_PATTERNS:
        match = pattern.search(folded.text)
        found = _valid_company(folded.group(match, "c")) if match else None
        if found:
            return found
    return None


_INVITE_VENDORS = frozenset(
    {
        "hackerrank",
        "hackerrankforwork",
        "codesignal",
        "codility",
        "hirevue",
        "zoom",
        "calendly",
        "goodtime",
        "modernloop",
    }
)
_VENDOR_LOCAL_PARTS = ("calendar-notification", "calendar-invites", "calendar")


def _is_vendor_sender(domain: str, local: str) -> bool:
    """Calendar, scheduling and assessment tools: the company is in the text, not the sender."""
    registrable = _registrable_label(domain)
    if registrable is not None and registrable[0] in _INVITE_VENDORS:
        return True
    return domain == "google.com" and local.startswith(_VENDOR_LOCAL_PARTS)


def _company_from_segments(subject: str) -> str | None:
    """'Acme | Software Engineer Intern' or 'Acme - Application received'.

    The first segment is free text, so callers must corroborate it (see _corroborated).
    """
    segments = _SEP_RE.split(re.sub(r"^(?:re|fwd?):\s*", "", subject, flags=re.IGNORECASE))
    if len(segments) < 2:
        return None
    rest = " ".join(segments[1:])
    if not (_has_noun(rest) or _APP_RE.search(rest)):
        return None
    return _valid_company(segments[0])


def _strip_requisitions(text: str) -> str:
    for pattern in _REQ_RES:
        text = pattern.sub(" ", text)
    return text


def _strip_role_decoration(role: str) -> str:
    """Trailing words ('Assessment'), location parentheticals and season prefixes."""
    previous = None
    while previous != role:
        previous = role
        role = _trim(_ROLE_TRAILING_RE.sub("", role))
        paren = _TRAILING_PAREN_RE.search(role)
        if paren and not _SEASON_RE.search(paren.group(1)) and _has_noun(role[: paren.start()]):
            role = _trim(role[: paren.start()])
    prefix = _SEASON_PREFIX_RE.match(role)
    if prefix and _has_noun(role[prefix.end() :]):
        role = role[prefix.end() :]
    return role


def _valid_role(raw: str) -> str | None:
    raw = _ROLE_PREFIX_RE.sub("", _collapse(raw))
    split = _AT_SPLIT_RE.match(raw)
    if split and _has_noun(split.group("r")):
        raw = split.group("r")
    role = _strip_role_decoration(_trim(_strip_requisitions(raw)))
    role = _trim(re.sub(r"\(\s*\)", "", role))
    if not role or len(role) > MAX_ROLE or len(role.split()) > MAX_ROLE_WORDS:
        return None
    if not _has_noun(role) or _DENY_RE.search(_key(role)):
        return None
    return role


def _role_from_patterns(text: str) -> str | None:
    folded = _Folded.of(text)
    line = _ROLE_LINE.search(folded.text)
    if line:
        role = _valid_role(folded.group(line, "r"))
        if role:
            return role
    for pattern in _ROLE_PATTERNS:
        for match in pattern.finditer(folded.text):
            role = _valid_role(folded.group(match, "r"))
            if role:
                return role
    return None


def _title_cased(role: str) -> bool:
    """Free-form segments must look like a job title, not a sentence ('Internship fair')."""
    return all(w[0].isupper() or w[0].isdigit() or w.lower() in _CONNECTIVES for w in role.split())


def _with_field(role: str, segments: list[str], separators: list[str], i: int) -> str:
    """'Co-op Student - Data Engineering': a dash before a field word stays in the role."""
    if i + 1 >= len(segments) or separators[i].strip() not in {"-", chr(0x2013), chr(0x2014)}:
        return role
    field = segments[i + 1]
    words = field.split()
    if not words or words[0].lower() not in _FIELD_WORDS or len(words) > 3:
        return role
    if _APP_RE.search(field) or "team" in field.lower():
        return role
    return _valid_role(f"{role} - {field}") or role


def _role_from_segments(subject: str) -> str | None:
    parts = _SEP_CAPTURE_RE.split(subject)
    segments, separators = parts[0::2], parts[1::2]
    for i, segment in enumerate(segments):
        role = _valid_role(segment)
        if role and _title_cased(role):
            return _with_field(role, segments, separators, i)
    return None


def _extract_role(subject: str, snippet: str, body: str) -> tuple[str | None, str | None]:
    role = _role_from_patterns(subject) or _role_from_segments(subject)
    if role:
        return role, SOURCE_SUBJECT
    role = _role_from_patterns(snippet)
    if role:
        return role, SOURCE_SNIPPET
    role = _role_from_patterns(body) or _job_card(snippet + "\n" + body)[0]
    return (role, SOURCE_BODY) if role else (None, None)


def _same_company(a: str, b: str) -> bool:
    ka, kb = _key(a).replace(" ", ""), _key(b).replace(" ", "")
    return ka in kb or kb in ka


def _extract_company(
    domain: str, local: str, from_name: str, subject: str, snippet: str, body: str
) -> tuple[str | None, str | None]:
    """Explicit text beats the display name, which beats the domain. Conflicting text gives None.

    Order: subject, then snippet, then body patterns ("applying to X", "Acme has invited you"),
    then the sign-off and job card; for an invite vendor (calendar, assessment tool) also the
    invitation wording. Only then the ATS display name or tenant, and last the domain."""
    vendor = _is_vendor_sender(domain, local)
    from_subject = _company_from_text(subject) or _corroborated(
        _company_from_segments(subject), domain, from_name, subject
    )
    from_snippet = _company_from_text(snippet)
    if vendor:
        from_subject = from_subject or _company_from_vendor_text(subject)
        from_snippet = from_snippet or _company_from_vendor_text(snippet)
    if from_subject and from_snippet and not _same_company(from_subject, from_snippet):
        return None, None
    if from_subject or from_snippet:
        return (from_subject, SOURCE_SUBJECT) if from_subject else (from_snippet, SOURCE_SNIPPET)
    from_body = _company_from_text(body) or _signoff_company(body)
    if vendor and not from_body:
        from_body = _company_from_vendor_text(body)
    from_body = from_body or _job_card(snippet + "\n" + body)[1]
    if from_body:
        return from_body, SOURCE_BODY
    if vendor and not is_ats_domain(domain):
        return None, None
    return _implicit_company(domain, local, from_name, snippet + "\n" + body)


def _corroborated(candidate: str | None, domain: str, from_name: str, subject: str) -> str | None:
    """A free-text subject segment counts only with corroboration.

    Accepted when the sender is an ATS, when the domain or display name agrees, or for
    'Company | Role' / 'Company - Role' subjects whose other segment is a real role. A
    'Prefix: text' subject ("Weekly digest: ...", "Opportunity: ...") is never enough alone.
    """
    if candidate is None:
        return None
    if is_ats_domain(domain) or _consistent(candidate, domain):
        return candidate
    head = _SEP_CAPTURE_RE.search(subject)
    if head and ":" not in head.group(1) and _role_from_segments(subject):
        return candidate
    display = _display_company(from_name, domain) if from_name else None
    return candidate if display and _same_company(candidate, display) else None


def _implicit_company(
    domain: str, local: str, from_name: str, text: str
) -> tuple[str | None, str | None]:
    """Display name, then (lowest confidence) the domain; nothing for vendor or generic senders.
    An ATS names the employer in its display name, so that is trusted even when it reads like a
    person's name (unless it is a "<person> via <ATS>" sender)."""
    if is_ats_domain(domain):
        display = _display_company(from_name, domain, trusted=not _VIA_RE.search(from_name))
        if display:
            return display, SOURCE_DISPLAY_NAME
        tenant = _tenant_company(domain, local, text)
        return (tenant, SOURCE_DOMAIN) if tenant else (None, None)
    registrable = _registrable_label(domain)
    if registrable is None or registrable[1] or _is_vendor(registrable[0]):
        return None, None
    display = _display_company(from_name, domain)
    if display:
        return _fuller_name(display, domain), SOURCE_DISPLAY_NAME
    from_domain = _domain_company(domain)
    return (from_domain, SOURCE_DOMAIN) if from_domain else (None, None)


def _fuller_name(display: str, domain: str) -> str:
    """'Stark' from a display name, stark-dynamics.example as the domain: the domain's longer form
    when the display name is its first words (not for a Corp/Inc style suffix)."""
    registrable = _registrable_label(domain)
    if registrable is None or registrable[1]:
        return display
    words, label = _key(display).split(), registrable[0].split("-")
    extra = label[len(words) :]
    if len(label) > len(words) and label[: len(words)] == words and not set(extra) & _SUFFIXES:
        return _title(registrable[0]) or display
    return display


_PII_RE = re.compile(r"\S*@\S*|\+?\d[\d\s().-]{6,}\d")
MAX_LLM_FIELD_INPUT = 200


def _masked(raw: str) -> str:
    return _collapse(_PII_RE.sub(" ", raw[:MAX_LLM_FIELD_INPUT]))


def clean_llm_company(raw: str | None) -> str | None:
    """Untrusted model output: mask emails/phones, then the same validation as extraction."""
    company = _valid_company(_masked(raw)) if raw else None
    if company and set(_key(company).split()) & GENERIC_WORDS:
        return None
    return company


def clean_llm_role(raw: str | None) -> str | None:
    return _valid_role(_masked(raw)) if raw else None


def _local_part(from_address: str) -> str:
    _, address = parseaddr(from_address)
    return address.rsplit("@", 1)[0].lower() if "@" in address else ""


def _without_company(role: str | None, company: str | None) -> str | None:
    """'Hooli Backend Intern' from a subject that starts with the company: the role is the rest."""
    if role and company and _key(role).startswith(_key(company) + " "):
        rest = _valid_role(role[len(company) :].strip(" -:" + _DASH_CHARS))
        return rest or role
    return role


def extract(
    from_address: str, from_name: str, subject: str, snippet: str, body: str = ""
) -> Extracted:
    """Company and role for an application, each None when it cannot be determined safely."""
    domain = sender_domain(from_address or "")
    name = (from_name or "")[:MAX_NAME_INPUT]
    subj = (subject or "")[:MAX_SUBJECT_INPUT]
    snip = (snippet or "")[:MAX_SNIPPET_INPUT]
    text = (body or "")[:MAX_BODY_INPUT]
    local = _local_part(from_address or "")
    company, company_source = _extract_company(domain, local, name, subj, snip, text)
    role, role_source = _extract_role(subj, snip, text)
    return Extracted(company, _without_company(role, company), company_source, role_source)
