"""Pure company and role extraction from sender and subject. Returns None rather than guessing.

Never logs or returns more than the extracted company and role: no email text leaves this module.
"""

import re
from dataclasses import dataclass

from app.services.prefilter import is_ats_domain, sender_domain
from app.text import normalize_text

MAX_COMPANY = 80
MAX_ROLE = 120
MAX_ROLE_WORDS = 9
MAX_COMPANY_WORDS = 6
MAX_NAME_INPUT = 150
MAX_SUBJECT_INPUT = 300
MAX_SNIPPET_INPUT = 500

SOURCE_DISPLAY_NAME = "display_name"
SOURCE_SUBJECT = "subject"
SOURCE_DOMAIN = "domain"
SOURCE_SNIPPET = "snippet"

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
    r"\s+(?:position|role|application|opening|assessment|interview|invitation)$", re.IGNORECASE
)
_ROLE_PREFIX_RE = re.compile(
    r"^(?:(?:thank you|thanks) for applying\s+(?:to|for)|your application\s+(?:to|for)|"
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
_COMP = rf"(?P<c>[^\s|,;:!?()\[\]{_DASH_CHARS}][^|,;:!?()\[\]{_DASH_CHARS}]{{0,79}}?)"
_COMP_END = rf"(?=\s+(?:has|was|is|have|will|for)\s|\s+[{_DASHES}|]\s|\s*[,;:!?|()\[\]]|\.?\s*$)"
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
)
_AT_COMPANY_RE = re.compile(r"\s(?:at|@)\s+(?!.*\s(?:at|@)\s)(.+)$", re.IGNORECASE)

_ROLE = r"(?P<r>[^|;:!?,][^|;:!?,]{0,119}?)"
_ROLE_END = (
    rf"(?=\s+(?:at|with|has|was|is|have|will|@)\s|\s+[{_DASHES}|]\s|\s*[,;:!?|]"
    r"|\.\s*$|\.\s+(?:we|your|thank|please|you|the|this|our)\b|\s*$)"
)
_ROLE_PATTERNS = (
    re.compile(rf"\bposition of\s+(?:the\s+|an?\s+)?{_ROLE}{_ROLE_END}", re.I),
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


def _valid_company(name: str) -> str | None:
    name = _trim(name)
    key = _key(name)
    if len(name) < 2 or len(name) > MAX_COMPANY or not key or key.isdigit():
        return None
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


def _display_company(name: str, domain: str) -> str | None:
    """Company named by a display name; person names and third-party senders are rejected."""
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
    if company and _looks_like_person(company) and not _consistent(company, domain):
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


def _domain_company(domain: str) -> str | None:
    """Lowest-confidence source: never for generic, academic or vendor domains."""
    registrable = _registrable_label(domain)
    if registrable is None or registrable[1] or _is_vendor(registrable[0]):
        return None
    return _title(registrable[0])


def _tenant_company(domain: str, snippet: str) -> str | None:
    for pattern in _TENANT_DOMAIN_RES:
        match = pattern.match(domain)
        if match:
            return _title(match.group("t"))
    url = _TENANT_URL_RE.search(snippet)
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


def _extract_role(subject: str, snippet: str) -> tuple[str | None, str | None]:
    role = _role_from_patterns(subject) or _role_from_segments(subject)
    if role:
        return role, SOURCE_SUBJECT
    role = _role_from_patterns(snippet)
    return (role, SOURCE_SNIPPET) if role else (None, None)


def _same_company(a: str, b: str) -> bool:
    ka, kb = _key(a).replace(" ", ""), _key(b).replace(" ", "")
    return ka in kb or kb in ka


def _extract_company(
    domain: str, from_name: str, subject: str, snippet: str
) -> tuple[str | None, str | None]:
    """Explicit text beats the display name, which beats the domain. Conflicting text gives None."""
    from_subject = _company_from_text(subject) or _corroborated(
        _company_from_segments(subject), domain, from_name, subject
    )
    from_snippet = _company_from_text(snippet)
    if from_subject and from_snippet and not _same_company(from_subject, from_snippet):
        return None, None
    if from_subject or from_snippet:
        return (from_subject, SOURCE_SUBJECT) if from_subject else (from_snippet, SOURCE_SNIPPET)
    return _implicit_company(domain, from_name, snippet)


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


def _implicit_company(domain: str, from_name: str, snippet: str) -> tuple[str | None, str | None]:
    """Display name, then (lowest confidence) the domain; nothing for vendor or generic senders."""
    if is_ats_domain(domain):
        display = _display_company(from_name, domain)
        if display:
            return display, SOURCE_DISPLAY_NAME
        tenant = _tenant_company(domain, snippet)
        return (tenant, SOURCE_DOMAIN) if tenant else (None, None)
    registrable = _registrable_label(domain)
    if registrable is None or registrable[1] or _is_vendor(registrable[0]):
        return None, None
    display = _display_company(from_name, domain)
    if display:
        return display, SOURCE_DISPLAY_NAME
    from_domain = _domain_company(domain)
    return (from_domain, SOURCE_DOMAIN) if from_domain else (None, None)


def extract(from_address: str, from_name: str, subject: str, snippet: str) -> Extracted:
    """Company and role for an application, each None when it cannot be determined safely."""
    domain = sender_domain(from_address or "")
    name = (from_name or "")[:MAX_NAME_INPUT]
    subj = (subject or "")[:MAX_SUBJECT_INPUT]
    snip = (snippet or "")[:MAX_SNIPPET_INPUT]
    company, company_source = _extract_company(domain, name, subj, snip)
    role, role_source = _extract_role(subj, snip)
    return Extracted(company, role, company_source, role_source)
