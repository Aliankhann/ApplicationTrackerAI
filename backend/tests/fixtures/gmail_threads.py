"""Synthetic Gmail threads (invented companies, .example domains)."""

from datetime import datetime, timedelta

from app.providers.gmail.types import MessageMeta

OWNER = "student@mail.example"


def _msg(
    thread_id: str, n: int, sender: str, subject: str, sent_at: datetime, *, user: bool = False
) -> MessageMeta:
    return MessageMeta(
        message_id=f"{thread_id}-{n}",
        thread_id=thread_id,
        from_address=sender,
        from_name="",
        subject=subject,
        snippet=f"Synthetic snippet for {subject}",
        sent_at=sent_at,
        from_user=user,
        rfc822_message_id=f"<{thread_id}-{n}@mail.example>",
    )


def build_threads(now: datetime) -> dict[str, list[MessageMeta]]:
    day = timedelta(days=1)
    return {
        "t-confirm": [
            _msg(
                "t-confirm",
                1,
                "jobs@acme-robotics.example",
                "We received your application",
                now - 10 * day,
            )
        ],
        "t-interview": [
            _msg(
                "t-interview", 1, "hr@globex-labs.example", "Application received", now - 20 * day
            ),
            _msg("t-interview", 2, "hr@globex-labs.example", "Interview invitation", now - 5 * day),
        ],
        "t-reject": [
            _msg("t-reject", 1, "talent@initech.example", "Your application update", now - 25 * day)
        ],
        "t-newsletter": [
            _msg(
                "t-newsletter",
                1,
                "news@careers-weekly.example",
                "Top internships this week",
                now - 200 * day,
            )
        ],
        "t-sent": [_msg("t-sent", 1, OWNER, "Internship application", now - 3 * day, user=True)],
    }
