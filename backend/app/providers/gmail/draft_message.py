"""RFC 2822 draft messages for the Gmail API (`raw`, base64url)."""

import base64
import re
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import getaddresses, parseaddr

from app.providers.gmail.errors import GmailError
from app.providers.gmail.types import DraftRequest

# Every C0 control (CR, LF, NUL, VT, FF, FS..RS, tab), DEL, NEL, and the Unicode line/paragraph
# separators: all of str.splitlines' boundaries plus NUL.
_HEADER_FORBIDDEN = re.compile(r"[\x00-\x1f\x7f\x85\u2028\u2029]")
_BAD_ADDRESS_CHARS = re.compile(r"[,;\s\"'<>()\[\]\\]")
MAX_REFERENCES = 20
MAX_REFERENCES_CHARS = 2000
INVALID_RECIPIENT = "invalid_recipient"


def clean_header(value: str) -> str:
    """Drop line separators and control characters so a value can never start a new header."""
    return _HEADER_FORBIDDEN.sub("", value).strip()


def single_address(value: str) -> str:
    """The one plain address in `value`, else GmailError("invalid_recipient")."""
    cleaned = clean_header(value)
    parsed = parseaddr(cleaned)[1]
    if (
        len(getaddresses([cleaned])) != 1
        or parsed.count("@") != 1
        or _BAD_ADDRESS_CHARS.search(parsed)
        or parsed.startswith("@")
        or parsed.endswith("@")
    ):
        raise GmailError(INVALID_RECIPIENT)
    return parsed


def cap_references(references: str) -> str:
    """Keep the newest ids: at most 20, and at most 2000 characters in total."""
    ids = clean_header(references).split()[-MAX_REFERENCES:]
    while ids and len(" ".join(ids)) > MAX_REFERENCES_CHARS:
        ids.pop(0)
    return " ".join(ids)


def build_raw_message(request: DraftRequest) -> str:
    """Plain-text UTF-8 reply. Non-ASCII header text is RFC 2047 encoded by the SMTP policy.

    No From header: Gmail fills in the authenticated user. Raises GmailError, never ValueError.
    """
    headers = {
        "To": single_address(request.to),
        "Subject": clean_header(request.subject),
        "In-Reply-To": clean_header(request.in_reply_to),
        "References": cap_references(request.references),
    }
    try:
        message = EmailMessage(policy=SMTP)
        for name, value in headers.items():
            if value:
                message[name] = value
        message.set_content(request.body_text, charset="utf-8", cte="base64")
        return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    except ValueError:
        raise GmailError("invalid_message") from None
