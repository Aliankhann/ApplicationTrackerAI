"""Follow-up template rendering: safe single-pass substitution, plain text only.

Templates are body-only. The tone preset adds the greeting and the sign-off.
"""

import re
import unicodedata
from collections.abc import Mapping
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

Tone = Literal["short", "warm", "formal"]

VARIABLES = ("recruiter_first_name", "role", "company", "applied_date", "your_name")
MAX_VALUE_LENGTH = 80
MAX_SUBJECT_LENGTH = 998

_UTC = ZoneInfo("UTC")
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
_NEWLINES = re.compile("[\r\n\x85\u2028\u2029]+")
_HTML_LIKE = re.compile(r"<[A-Za-z/!]")
# Control, format (bidi, zero-width), surrogate, private-use, line and paragraph separators.
_STRIPPED_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Zl", "Zp"})
TONES = ("short", "warm", "formal")

_FALLBACKS = {
    "recruiter_first_name": "there",
    "role": "the role",
    "company": "your team",
    "applied_date": "recently",
    "your_name": "",
}

_GREETINGS = {
    "short": "Hi {name},",
    "warm": "Hi {name}, I hope you're doing well.",
    "formal": "Dear {name},",
}
_SIGN_OFFS = {"short": "Thanks,", "warm": "Best,", "formal": "Kind regards,"}


class TemplateError(ValueError):
    """The template has an unknown placeholder, unbalanced braces, or HTML."""


def strip_unsafe(text: str) -> str:
    """NFC-normalise and drop control, bidi, zero-width, and separator characters."""
    normal = unicodedata.normalize("NFC", text)
    return "".join(ch for ch in normal if unicodedata.category(ch) not in _STRIPPED_CATEGORIES)


def _has_unsafe_char(template: str) -> bool:
    return any(
        unicodedata.category(ch) in _STRIPPED_CATEGORIES and ch not in "\n\t" for ch in template
    )


def validate_tone(tone: str) -> None:
    if tone not in TONES:
        raise TemplateError(f"Unknown tone {tone!r}; use one of {', '.join(TONES)}")


def validate_template(template: str) -> None:
    if _has_unsafe_char(template):
        raise TemplateError("Templates may not contain control or invisible characters")
    if _HTML_LIKE.search(template):
        raise TemplateError("Templates are plain text; HTML tags are not allowed")
    leftover = _PLACEHOLDER.sub("", template)
    if "{" in leftover or "}" in leftover:
        raise TemplateError("Unbalanced or malformed braces in template")
    for name in _PLACEHOLDER.findall(template):
        if name not in VARIABLES:
            raise TemplateError(f"Unknown placeholder {{{name}}}")


def _clean(value: str | None) -> str:
    if not value:
        return ""
    spaced = _NEWLINES.sub(" ", value)
    plain = strip_unsafe(spaced).replace("{", "").replace("}", "")
    return plain.strip()[:MAX_VALUE_LENGTH].strip()


def format_applied_date(applied_at: datetime, tz: ZoneInfo | None = None) -> str:
    """Like "March 3", in the user's timezone (UTC when None). Naive datetimes are rejected."""
    if applied_at.tzinfo is None:
        raise ValueError("applied_at must be timezone-aware")
    local = applied_at.astimezone(tz or _UTC)
    return f"{local.strftime('%B')} {local.day}"


def render(
    template: str,
    context: Mapping[str, str | None],
    tone: Tone = "short",
) -> str:
    """Render greeting + body + sign-off. Never leaves a raw `{...}` in the output."""
    validate_tone(tone)
    validate_template(template)
    values = {}
    for name in VARIABLES:
        values[name] = _clean(context.get(name)) or _FALLBACKS[name]
    your_name = _clean(context.get("your_name"))

    body = _PLACEHOLDER.sub(lambda m: values[m.group(1)], template)
    greeting = _GREETINGS[tone].format(name=values["recruiter_first_name"])
    sign_off = _SIGN_OFFS[tone]
    text = f"{greeting}\n\n{body}"  # values were stripped of braces, so no raw `{...}` leaks
    if your_name:
        text += f"\n\n{sign_off}\n{your_name}"
    return text


def _truncate_utf8(text: str, max_bytes: int) -> str:
    return text.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")


def subject_for(original_subject: str) -> str:
    """Reply subject: one "Re: " prefix, no control or invisible characters, <= 998 bytes."""
    subject = " ".join(
        strip_unsafe(_NEWLINES.sub(" ", original_subject.replace("\t", " "))).split()
    )
    if not subject:
        return "Re: Following up"
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    return _truncate_utf8(subject, MAX_SUBJECT_LENGTH)
