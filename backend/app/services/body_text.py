"""Cleaning of a message body before it is classified or mined for company and role.

Pure functions on text that lives only in memory for the length of one sync step: nothing here
stores or logs it. Removes quoted replies, footers and unsubscribe blocks, and signature noise
(contact lines, disclaimers), but keeps the sign-off ("Best regards, The Acme Talent Acquisition
Team"), which names the company. The result is cut to a bounded window.
"""

import re

HEAD_CHARS = 1800
TAIL_CHARS = 600

_QUOTE_STARTS = (
    re.compile(r"(?ims)^[ \t]*on\s[^\n]{0,200}(?:\n[^\n]{0,120})?wrote:\s*$"),
    re.compile(r"(?im)^[ \t]*-{2,}\s*(?:original message|forwarded message)\s*-{2,}\s*$"),
    re.compile(r"(?im)^[ \t]*from:[^\n]{3,200}\n[ \t]*(?:sent|date):"),
    re.compile(r"(?m)^-- ?$"),
)
_FOOTER_TERMS = re.compile(
    r"\b(?:unsubscribe|manage\s+your\b|(?:update|change)\s+your\s+(?:email\s+)?(?:preferences|settings)"
    r"|email\s+preferences|notification\s+settings"
    r"|view\s+(?:this\s+(?:email|message)\s+)?in\s+(?:your\s+)?browser"
    r"|you(?:'re|\s+are)\s+receiving\s+(?:this|these)|this\s+(?:email|message)\s+was\s+sent"
    r"|privacy\s+policy|terms\s+of\s+(?:service|use)|all\s+rights\s+reserved"
    r"|do\s+not\s+reply|don't\s+reply|do\s+not\s+respond"
    r"|this\s+is\s+an\s+automated\s+(?:message|email)|powered\s+by\s+\w+|sent\s+(?:via|from)\s+\w+)\b",
    re.IGNORECASE,
)
_FRAGMENT_END = re.compile(r"(?<=[.!?|])")
_CONTACT_TOKENS = re.compile(
    r"(?:https?://|www\.)\S+|\S+@\S+|\+?\d[\d()\-. ]{5,}\d"
    r"|\b(?:tel|phone|mobile|cell|fax|email|e-mail|web|website|linkedin)\b[:.]?|[\s|,;:()\u2022-]+",
    re.IGNORECASE,
)
# Careers links name the employer (acme.wd5.myworkdayjobs.com); everything else link-only goes.
_KEEP_LINK = re.compile(
    r"myworkdayjobs\.com|lever\.co/|greenhouse\.io/|ashbyhq\.com/", re.IGNORECASE
)
_NOISE_LINE = re.compile(
    r"^\[image:[^\]]*\]$|^\[cid:[^\]]*\]$|^sent from my\b.*$|"
    r".*\b(?:confidential|intended\s+recipient|privileged)\b.{0,200}$",
    re.IGNORECASE,
)


def _cut_quoted(text: str) -> str:
    """Drop everything from the first quoted-reply marker on."""
    end = len(text)
    for pattern in _QUOTE_STARTS:
        found = pattern.search(text)
        if found and found.start() < end:
            end = found.start()
    return text[:end]


def _clean_line(line: str) -> str | None:
    line = line.strip()
    if not line or line.startswith(">"):
        return None
    line = "".join(f for f in _FRAGMENT_END.split(line) if not _FOOTER_TERMS.search(f)).strip()
    if not line:
        return None
    if _NOISE_LINE.match(line) or (
        not _CONTACT_TOKENS.sub("", line) and not _KEEP_LINK.search(line)
    ):
        return None
    return line


def clean_body(text: str) -> str:
    """The message text without quoted replies, footers and signature noise."""
    lines = [_clean_line(line) for line in _cut_quoted(text or "").split("\n")]
    kept: list[str] = []
    for line in lines:
        if line is not None:
            kept.append(line)
        elif kept and kept[-1] != "":
            kept.append("")
    return "\n".join(kept).strip()


def body_window(text: str, head: int = HEAD_CHARS, tail: int = TAIL_CHARS) -> str:
    """The start and the end of the text (the sign-off lives at the end), bounded."""
    if len(text) <= head + tail:
        return text
    return f"{text[:head]}\n{text[-tail:]}"


def prepare_body(raw: str) -> str:
    """Clean, then bound: what classification and extraction get to read."""
    return body_window(clean_body(raw))
