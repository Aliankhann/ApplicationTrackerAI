"""Daily digest content: company names and statuses only, never email text.

The digest email is itself a leak path, so nothing derived from a subject, snippet, or address
is ever read here. Company names are user-visible extraction output: they are cleaned of control
and invisible characters, and HTML-escaped in the HTML part.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.repositories import digest as repo
from app.services.classification import ApplicationStatus
from app.services.templates import strip_unsafe

AWAITING_AFTER = timedelta(days=7)
AWAITING_UNTIL = timedelta(days=60)
MAX_LISTED = 10
UNKNOWN_COMPANY = "Unknown company"
_LABELS = {
    ApplicationStatus.APPLIED: "Applied",
    ApplicationStatus.ONLINE_ASSESSMENT: "Online assessment",
    ApplicationStatus.INTERVIEW: "Interview",
    ApplicationStatus.OFFER: "Offer",
    ApplicationStatus.REJECTED: "Rejected",
}


@dataclass(frozen=True)
class Entry:
    company: str
    status: str | None = None

    def line(self) -> str:
        return f"{self.company} ({self.status})" if self.status else self.company


@dataclass(frozen=True)
class Digest:
    drafts: tuple[Entry, ...]
    replies: tuple[Entry, ...]
    rejections: tuple[Entry, ...]
    interviews: tuple[Entry, ...]
    awaiting: tuple[Entry, ...]

    def sections(self) -> tuple[tuple[str, str, str, tuple[Entry, ...]], ...]:
        """(title, singular, plural, entries) in display order."""
        return (
            ("Follow-up drafts waiting for your review", "draft", "drafts", self.drafts),
            ("New replies", "reply", "replies", self.replies),
            (
                "Interview and offer updates",
                "interview update",
                "interview updates",
                self.interviews,
            ),
            ("Rejections", "rejection", "rejections", self.rejections),
            ("No reply after 7+ days", "awaiting a reply", "awaiting a reply", self.awaiting),
        )

    @property
    def subject(self) -> str:
        parts = [
            f"{len(items)} {singular if len(items) == 1 else plural}"
            for _, singular, plural, items in self.sections()
            if items
        ]
        return "Your application update: " + ", ".join(parts)

    @property
    def total(self) -> int:
        return sum(len(items) for *_, items in self.sections())


_EMAIL_LIKE = re.compile(r"\S+@\S+")
_PHONE_LIKE = re.compile(r"\+?\d(?:[\d\s().-]*\d){6,}")


def clean_company(company: str | None) -> str:
    """Company names come from email extraction: drop control characters, addresses and phone
    numbers so the digest never carries contact details."""
    cleaned = strip_unsafe(company or "")
    cleaned = _PHONE_LIKE.sub("", _EMAIL_LIKE.sub("", cleaned))
    cleaned = " ".join(cleaned.split())
    return cleaned if any(c.isalnum() for c in cleaned) else UNKNOWN_COMPANY


def _entry(row: repo.AppRow) -> Entry:
    return Entry(clean_company(row.company), _LABELS[row.status])


def _unique(rows: list[repo.AppRow]) -> list[repo.AppRow]:
    seen: set[tuple[uuid.UUID, ApplicationStatus]] = set()
    unique = []
    for row in rows:
        if (row.application_id, row.status) not in seen:
            seen.add((row.application_id, row.status))
            unique.append(row)
    return unique


def build_digest(
    session: Session, user_id: uuid.UUID, since: datetime, now: datetime, tz: ZoneInfo
) -> Digest | None:
    """What changed since `since`; None when there is nothing to report. `tz` is reserved for
    local-calendar wording and does not change what is selected."""
    changes = _unique(repo.notable_changes_since(session, user_id, since, now))
    changed_ids = {row.application_id for row in changes}
    replies = [
        row
        for row in repo.replies_since(session, user_id, since, now)
        if row.application_id not in changed_ids
    ]
    awaiting = repo.awaiting_reply(session, user_id, now - AWAITING_UNTIL, now - AWAITING_AFTER)
    digest = Digest(
        drafts=tuple(Entry(clean_company(c)) for c in repo.drafted_companies(session, user_id)),
        replies=tuple(map(_entry, replies)),
        rejections=tuple(_entry(r) for r in changes if r.status is ApplicationStatus.REJECTED),
        interviews=tuple(_entry(r) for r in changes if r.status is not ApplicationStatus.REJECTED),
        awaiting=tuple(map(_entry, awaiting)),
    )
    return digest if digest.total else None


def _listed(items: tuple[Entry, ...]) -> tuple[list[str], int]:
    return [e.line() for e in items[:MAX_LISTED]], max(0, len(items) - MAX_LISTED)


def render_text(digest: Digest, unsubscribe_url: str) -> str:
    lines = ["Here is your application update.", ""]
    for title, _, _, items in digest.sections():
        if not items:
            continue
        shown, more = _listed(items)
        lines.append(f"{title} ({len(items)})")
        lines += [f"- {line}" for line in shown]
        if more:
            lines.append(f"- and {more} more")
        lines.append("")
    lines += ["Open the app to see details.", "", f"Turn off this daily digest: {unsubscribe_url}"]
    return "\n".join(lines) + "\n"


def render_html(digest: Digest, unsubscribe_url: str) -> str:
    body = ["<p>Here is your application update.</p>"]
    for title, _, _, items in digest.sections():
        if not items:
            continue
        shown, more = _listed(items)
        rows = [f"<li>{escape(line)}</li>" for line in shown]
        if more:
            rows.append(f"<li>and {more} more</li>")
        body.append(f"<h3>{escape(title)} ({len(items)})</h3><ul>{''.join(rows)}</ul>")
    body.append("<p>Open the app to see details.</p>")
    link = escape(unsubscribe_url, quote=True)
    body.append(f'<p><a href="{link}">Turn off this daily digest</a></p>')
    return "<!doctype html><html><body>" + "".join(body) + "</body></html>"
