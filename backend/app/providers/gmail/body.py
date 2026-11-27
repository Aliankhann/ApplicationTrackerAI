"""Plain text of a Gmail message payload (`format=full`), read in memory and never stored.

Prefers the text/plain part, else strips the HTML part to text (stdlib parser; script and style
dropped; whitespace collapsed). Attachments are skipped and never requested. Charsets are decoded
with replacement, so a bad part cannot raise. Nothing here logs.
"""

import base64
import binascii
import re
from html.parser import HTMLParser
from typing import Any

MAX_PARTS = 60
MAX_DEPTH = 10
MAX_ENCODED_CHARS = 120_000  # a part's base64 is cut here before decoding, whatever max_chars is
MAX_TOTAL_BYTES = 300_000  # decoded bytes across all parts of one message
MIN_USEFUL_PLAIN = 40  # a shorter text/plain next to a real HTML part is only a stub
_CHARSET_RE = re.compile(r"charset\s*=\s*\"?([\w.:-]+)", re.IGNORECASE)
_BLOCK_TAGS = frozenset(
    {"p", "div", "br", "tr", "li", "ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6", "hr"}
)
_SKIPPED_TAGS = frozenset({"script", "style", "head", "title", "noscript"})


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED_TAGS:
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self.chunks.append("\n")
        elif tag in {"td", "th"}:
            self.chunks.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.chunks.append(re.sub(r"\s+", " ", data))  # newlines in markup are only spaces


def collapse_whitespace(text: str) -> str:
    """Spaces collapsed within lines; at most one blank line in a row."""
    lines = [re.sub(r"[ \t\r\f\v\xa0]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def html_to_text(markup: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(markup)
        parser.close()
    except (ValueError, AssertionError, RecursionError):
        pass  # malformed markup: keep what was parsed so far
    return collapse_whitespace("".join(parser.chunks))


def _charset(part: dict[str, Any]) -> str:
    for header in part.get("headers") or []:
        if str(header.get("name", "")).lower() == "content-type":
            found = _CHARSET_RE.search(str(header.get("value", "")))
            if found:
                return found.group(1)
    return "utf-8"


def _decode(part: dict[str, Any], budget: list[int]) -> str:
    """Text of one part; `budget[1]` is what is left of the message's decoded-bytes allowance."""
    data = part.get("body", {}).get("data")
    if not isinstance(data, str) or not data or budget[1] <= 0:
        return ""
    data = data[: min(MAX_ENCODED_CHARS, budget[1] * 4 // 3 + 4)]
    if len(data) % 4 == 1:
        data = data[:-1]  # a cut inside a base64 group
    try:
        raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    except (binascii.Error, ValueError):
        return ""
    budget[1] -= len(raw)
    try:
        return raw.decode(_charset(part), errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _is_attachment(part: dict[str, Any]) -> bool:
    return bool(part.get("filename")) or "attachmentId" in (part.get("body") or {})


def _collect(part: Any, found: dict[str, list[str]], budget: list[int], depth: int = 0) -> None:
    if not isinstance(part, dict) or depth > MAX_DEPTH or budget[0] <= 0:
        return  # budget is [parts left, decoded bytes left]
    budget[0] -= 1
    mime = str(part.get("mimeType", "")).lower()
    if mime in {"text/plain", "text/html"} and not _is_attachment(part):
        found.setdefault(mime, []).append(_decode(part, budget))
    for child in part.get("parts") or []:
        _collect(child, found, budget, depth + 1)


def message_text(payload: Any, max_chars: int) -> str:
    """Readable text of a message payload, at most `max_chars` characters."""
    found: dict[str, list[str]] = {}
    _collect(payload, found, [MAX_PARTS, MAX_TOTAL_BYTES])
    plain = collapse_whitespace("\n\n".join(found.get("text/plain", [])))
    html_parts = found.get("text/html", [])
    if len(plain) < MIN_USEFUL_PLAIN and html_parts:
        from_html = html_to_text("\n".join(html_parts))
        if len(from_html) > len(plain):
            plain = from_html
    return plain[:max_chars]
