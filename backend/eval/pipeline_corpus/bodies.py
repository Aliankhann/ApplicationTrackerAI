"""Message bodies for the tune split.

The tune corpus was written as snippets. A body is derived from each snippet the way a real mail
continues it: the full snippet text, the text after the snippet window, then a sign-off (on every
second thread) and the footer the template family adds. Holdout bodies are written by hand.
"""

import zlib

from eval.pipeline_corpus.model import Case, Msg

_FOOTERS = {
    "indeed": "Manage your Indeed job alerts | Unsubscribe | Privacy policy",
    "linkedin": "You are receiving job alert emails. Unsubscribe or manage your job alerts.",
    "handshake": "Unsubscribe from these emails. View in browser.",
}
_DEFAULT_FOOTER = "This is an automated message. Please do not reply. Unsubscribe | Privacy Policy"
_NO_SIGN_OFF = frozenset({"calendar", "linkedin", "indeed", "handshake", "recruiter"})


def _sign_off(case: Case, msg: Msg) -> str:
    if case.kind != "application" or not case.company or msg.from_user:
        return ""
    if case.family in _NO_SIGN_OFF or case.family.startswith("noise"):
        return ""
    if zlib.crc32(case.id.encode()) % 2:
        return ""
    return f"\n\nBest regards,\nThe {case.company} Talent Acquisition Team"


def body_of(case: Case, msg: Msg) -> str:
    """The message body: written (holdout) or derived from the snippet (tune)."""
    if msg.body:
        return msg.body
    text = msg.snippet + (" " + msg.tail if msg.tail else "")
    if msg.from_user:
        return text
    footer = _FOOTERS.get(case.family, _DEFAULT_FOOTER)
    return f"{text}{_sign_off(case, msg)}\n\n{footer}"
