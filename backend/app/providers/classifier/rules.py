"""Ordered regex rules. Earlier rules win; only strong matches (>= 0.8) decide on their own.

Design principle: when in doubt, never "rejection" (a wrong rejection is the costliest error).
Rejection phrases are confined to one sentence, need a we-subject or an application object, and
are demoted to "needs review" by contrast signals ("but", "another opening", ...). Confirmation
and recruiter rules are deliberately weak so rejection boilerplate such as "thank you for
applying ... unfortunately we will not be moving forward" resolves to rejection instead of a
conflict. Rule ids are stable: never reuse or rename them.
"""

import re
from dataclasses import dataclass

from app.config import get_settings
from app.providers.classifier.types import ClassificationInput, ClassificationResult, Label
from app.text import normalize_text

STRONG = 0.8
SPECIFIC = 0.9  # specific rejection rules may outrank a negated interview/offer match
VETOED_CONFIDENCE = 0.5
_FIELDS = ("subject", "snippet", "body")

# Conditional phrasing ("if you are not selected") must never read as a rejection.
_CONDITIONAL = r"\bif\s+(?:you|we)\s+(?:are\s+|were\s+|do\s+)?not\b|\bshould\s+you\s+not\b"
# Contrast, continuation, or quoting in the same field demotes a rejection to "needs review".
_CONTRAST = re.compile(
    r"\bbut\b|\b(?:respond|reply)\s+to\s+(?:every|each|all)\b|\bhowever\b|\b(?:another|other)\s+(?:role|opening|position|team|cohort)s?\b"
    r"|\bwould\s+like\s+to\s+(?:interview|invite|consider|speak|chat)\b"
    r"|\blove\s+to\s+consider\b|\bstill\s+under\s+consideration\b|\bfor\s+20\d\d\b"
    r"|\bnewsletter\b|\bunsubscribe\b|\bwebinar\b"
)
# Conditional wording ("if you are selected, we will schedule an interview") describes what may
# happen later; it must not read as an interview, offer or assessment.
_HYPOTHETICAL = re.compile(
    r"\b(?:if|should|once|whether|unless|in\s+case|in\s+the\s+event)\b|\b(?:may|might|could)\s+(?:also\s+)?be\b"
    r"|\b(?:will|may|might|could)\s+(?:also\s+)?(?:be\s+)?(?:asked|invited|contacted|required)\b"
)
# "will not be extending an offer" must never read as an offer.
_NEG_OFFER = (
    r"\b(?:not|won't|wont|cannot|can't|unable|never)\s+(?:be\s+|to\s+)?"
    r"(?:extending|offering|making|extend|offer|make)\b"
)
_RESCINDED = r"\brescind(?:ed|ing)?\b|\bwithdr(?:aw|awn|ew)\b|\brevok(?:e|ed)\b"

_S = r"[^.!?;\n]"  # one sentence
_SENT = r"(?:\A|(?<=[.!?;\n]))"
_APP = r"application|candidacy|candidature|role|position|candidates?|applicants?"
_SUBJ = r"(?:we|we're|we are|we've|we have|we will|we won't|our team|the team|the hiring team)"
_NOT_FORWARD = r"(?:not|won't|wont)\s+(?:be\s+)?(?:moving|move|proceeding|proceed)\s+forward"
_CANDIDATES = r"(?:other|another|different)\s+(?:candidates?|applicants?)"


def _in_sentence(core: str, objects: str) -> str:
    """`core` inside a sentence that also contains one of `objects`."""
    return rf"{_SENT}(?={_S}*\b(?:{objects})\b){_S}*?{core}"


@dataclass(frozen=True)
class Rule:
    id: str
    label: Label
    pattern: re.Pattern[str]
    confidence: float
    fields: tuple[str, ...] = _FIELDS


def _p(body: str) -> re.Pattern[str]:
    return re.compile(body, re.IGNORECASE)


def _guarded(guard: str, body: str) -> re.Pattern[str]:
    return re.compile(rf"(?s)\A(?!.*(?:{guard})).*?(?:{body})", re.IGNORECASE)


def _rejection(body: str) -> re.Pattern[str]:
    return _guarded(_CONDITIONAL, body)


def _with_context(context: str, body: str) -> re.Pattern[str]:
    """`body`, but only in a field that also holds one of the `context` words."""
    return re.compile(rf"(?s)\A(?=.*\b(?:{context})\b).*?(?:{body})", re.IGNORECASE)


_APPLICATION_CONTEXT = (
    r"application|applying|applied|candidacy|candidate|applicant|position|role|internship"
    r"|hiring|next\s+steps?|interest\s+in"
)


def _offer(body: str) -> re.Pattern[str]:
    interview = r"(?!\s+(?:to\s+)?(?:an?\s+|the\s+)?(?:interview|call|chat|opportunity\s+to)\b)"
    return _guarded(f"{_RESCINDED}|{_NEG_OFFER}", rf"(?:{body}){interview}")


_OA_DOMAINS = r"(?:^|\.)(?:hackerrank|hackerrankforwork|codesignal|codility)\.com$"

RULES: tuple[Rule, ...] = (
    Rule(
        "irr.job_alert_digest",
        Label.IRRELEVANT,
        _p(
            r"\bnew\s+jobs?\s+for\s+you\b|\bjobs?\s+you\s+may\s+be\s+interested\s+in\b"
            r"|\b\d+\s+new\s+(?:jobs?|internships?)\b|\bjob\s+alerts?\b"
        ),
        0.9,
        fields=("subject",),
    ),
    Rule(
        "irr.job_digest_wording",
        Label.IRRELEVANT,
        _p(
            r"\bnew\s+jobs?\s+for\s+you\b|\bjobs?\s+you\s+may\s+be\s+interested\s+in\b"
            r"|\b\d+\s+new\s+(?:jobs?|internships?)\b|\bjob\s+alert\s+(?:for|from)\b"
        ),
        0.9,
        fields=("snippet", "body"),
    ),
    Rule(
        "rej.not_moving_forward",
        Label.REJECTION,
        _rejection(
            rf"(?:{_in_sentence(rf'\b{_SUBJ}\s+(?:\w+\s+)?{_NOT_FORWARD}', _APP)}"
            rf"|{_SENT}\s*not\s+moving\s+forward\s+with\s+your\s+(?:application|candidacy))\b"
        ),
        0.9,
    ),
    Rule(
        "rej.not_proceeding",
        Label.REJECTION,
        _rejection(
            _in_sentence(
                rf"\b{_SUBJ}\s+(?:\w+\s+)?(?:not|won't|wont)\s+(?:be\s+)?proceeding\s+with\b", _APP
            )
        ),
        0.9,
    ),
    Rule(
        "rej.decided_not_to_proceed",
        Label.REJECTION,
        _rejection(
            r"\bwe(?:'ve|\s+have)?\s+(?:\w+\s+)?(?:decided|chosen)\s+not\s+to\s+(?:proceed|move\s+forward)\b"
        ),
        0.9,
    ),
    Rule(
        "rej.pursue_other_candidates",
        Label.REJECTION,
        _rejection(rf"\bto\s+(?:pursue|proceed\s+with)\s+{_CANDIDATES}\b"),
        0.9,
    ),
    Rule(
        "rej.forward_with_other",
        Label.REJECTION,
        _rejection(rf"\b(?:moving|move|proceed|proceeding)\s+forward\s+with\s+{_CANDIDATES}\b"),
        0.9,
    ),
    Rule(
        "rej.selected_other",
        Label.REJECTION,
        _rejection(rf"\b(?:selected|chosen|chose|selecting)\s+{_CANDIDATES}\b"),
        0.9,
    ),
    Rule(
        "rej.careful_consideration",
        Label.REJECTION,
        _rejection(rf"\bafter\s+careful\s+consideration\b{_S}*?\b{_CANDIDATES}\b"),
        0.9,
    ),
    Rule(
        "rej.position_filled",
        Label.REJECTION,
        _rejection(
            r"\b(?:position|role)\s+(?:has\s+been|was|is\s+now)\s+filled\b|\bfilled\s+the\s+(?:role|position)\b"
        ),
        0.9,
    ),
    Rule(
        "rej.application_unsuccessful",
        Label.REJECTION,
        _rejection(r"\b(?:application|candidacy)\s+(?:was|has\s+been|is)\s+unsuccessful\b"),
        0.9,
    ),
    Rule(
        "rej.unable_to_offer",
        Label.REJECTION,
        _rejection(
            r"\b(?:won't|will\s+not|cannot|can't|unable|not\s+able)\s+(?:be\s+able\s+)?(?:to\s+)?offer\s+you"
            r"\s+(?:the|a|an)\s+(?:[\w&/+-]+\s+){0,6}?(?:role|position|internship|job|place|spot)\b"
        ),
        0.9,
    ),
    Rule(
        "rej.proceed_with_applicants",
        Label.REJECTION,
        _rejection(
            r"\b(?:proceed|move\s+forward|continue|go)(?:ing)?\s+with\s+(?:other\s+)?"
            r"(?:applicants?|candidates?)\s+(?:whose|who|that)\b"
        ),
        0.9,
    ),
    Rule(
        "rej.regret_to_inform",
        Label.REJECTION,
        _rejection(
            _in_sentence(
                r"\bregret\s+to\s+inform\b",
                rf"{_APP}|opportunity|moving\s+forward|proceed|selected|unable",
            )
        ),
        0.85,
    ),
    Rule(
        "rej.unfortunately_not",
        Label.REJECTION,
        _rejection(
            _in_sentence(
                rf"\bunfortunately\b{_S}*?\b(?:not|unable|cannot|can't|won't|wont)\b",
                r"application|candidacy|position|role|offer|opportunity|moving\s+forward|proceed(?:ing)?",
            )
        ),
        0.85,
    ),
    Rule(
        "rej.no_longer_considered",
        Label.REJECTION,
        _rejection(r"\bno\s+longer\s+(?:under\s+consideration|being\s+considered|considered)\b"),
        0.9,
    ),
    Rule(
        "rej.ne_pas_donner_suite",
        Label.REJECTION,
        _rejection(r"\bne\s+(?:\w+\s+){0,3}pas\s+donner\s+suite\b"),
        0.9,
    ),
    Rule(
        "rej.decided_not_to_pursue",
        Label.REJECTION,
        _rejection(
            r"\b(?:we(?:'ve|\s+have)?|(?:our|the)\s+team\s+(?:has|have))\s+(?:\w+\s+)?"
            r"(?:decided|chosen|elected|opted)\s+"
            r"(?:not\s+to\s+(?:pursue|continue|advance|extend|hire)\b"
            rf"|to\s+(?:pass\s+on|close|decline){_S}*?\b(?:application|candidacy)\b)"
        ),
        0.9,
    ),
    Rule(
        "rej.not_offering_position",
        Label.REJECTION,
        _rejection(
            rf"\b{_SUBJ}\s+(?:\w+\s+)?(?:not|won't|wont)\s+(?:be\s+)?(?:offering|extending|making)"
            r"\s+(?:you\s+)?(?:an?\s+|the\s+)?(?:offer|position|role|internship)\b"
        ),
        0.9,
    ),
    Rule(
        "rej.unable_to_advance",
        Label.REJECTION,
        _rejection(
            _in_sentence(
                rf"\b{_SUBJ}\s+(?:are\s+)?(?:unable|cannot|can't|not\s+able|won't\s+be\s+able"
                r"|declining)\s+(?:to\s+)?(?:move\s+forward|proceed|advance"
                r"|take\s+your\s+(?:application|candidacy)\s+(?:any\s+)?further)\b",
                _APP,
            )
        ),
        0.9,
    ),
    Rule(
        "rej.not_selected",
        Label.REJECTION,
        _rejection(
            _in_sentence(
                r"\byou\s+(?:have\s+|were\s+|are\s+)?(?:not|n't)\s+(?:been\s+)?(?:selected|chosen)\b",
                r"stage|round|interview|internship|position|role|candidacy|application",
            )
        ),
        0.9,
    ),
    Rule(
        "rej.go_with_other",
        Label.REJECTION,
        _rejection(
            _in_sentence(
                rf"\b(?:go|going|went)\s+with\s+{_CANDIDATES}\b"
                r"|\b(?:hire|hiring)\s+(?:someone|somebody)\s+else\b",
                _APP + "|internship",
            )
        ),
        0.9,
    ),
    Rule(
        "rej.application_not_successful",
        Label.REJECTION,
        _rejection(
            r"\b(?:application|candidacy)\s+(?:has\s+|was\s+)?(?:not|n't)\s+(?:been\s+)?successful\b"
        ),
        0.9,
    ),
    Rule(
        "rej.not_taking_forward",
        Label.REJECTION,
        _rejection(
            _in_sentence(
                rf"(?:{_SUBJ}|\band\s+will)\s+(?:\w+\s+)?(?:not|won't|wont)\s+(?:be\s+)?"
                r"(?:continuing|pursuing|advancing|progressing|taking)\b"
                r"|\byou\s+(?:will\s+)?not\s+be\s+(?:moving\s+on|advancing|progressing)\b",
                _APP + "|stage",
            )
        ),
        0.9,
    ),
    Rule(
        "off.pleased_to_offer",
        Label.OFFER,
        _offer(r"\bpleased\s+to\s+(?:offer|extend)\s+you\b"),
        0.9,
    ),
    Rule(
        "off.offer_letter",
        Label.OFFER,
        _offer(
            r"\boffer\s+letter\b|\bextend(?:ing)?\s+(?:you\s+)?an\s+offer\b"
            r"|\boffer\s+of\s+employment\b|\bjob\s+offer\b"
        ),
        0.9,
    ),
    Rule(
        "off.would_like_to_offer",
        Label.OFFER,
        _offer(
            r"\b(?:(?:would|'d)\s+(?:like|love)|(?:delighted|thrilled|excited|happy))\s+to\s+"
            r"(?:offer|extend)\s+you\s+(?:the|a|an)\s+(?:[\w&/+-]+\s+){0,6}?"
            r"(?:position|role|internship|job|offer)\b"
        ),
        0.9,
    ),
    Rule(
        "int.schedule_interview",
        Label.INTERVIEW,
        _p(r"\bschedule\s+(?:an|your)\s+interview\b"),
        0.9,
    ),
    Rule(
        "int.invite_interview",
        Label.INTERVIEW,
        _p(r"\binvite\s+you\s+(?:to|for)\s+(?:an?\s+)?interview\b"),
        0.9,
    ),
    Rule(
        "int.interview_you",
        Label.INTERVIEW,
        _p(r"\b(?:like|love)\s+to\s+interview\s+you\b|\binterview\s+you\s+for\b"),
        0.9,
    ),
    Rule(
        "int.offer_interview",
        Label.INTERVIEW,
        _p(
            r"\b(?:pleased|like|happy)\s+to\s+(?:offer|extend)\s+you\s+(?:an?\s+|the\s+)?(?:interview|opportunity\s+to\s+interview)\b"
        ),
        0.9,
    ),
    Rule("int.phone_screen", Label.INTERVIEW, _p(r"\bphone\s+screen\b"), 0.85),
    Rule("int.superday", Label.INTERVIEW, _p(r"\bsuperday\b"), 0.85),
    Rule("int.hirevue", Label.INTERVIEW, _p(r"\bhirevue\b"), 0.85),
    Rule(
        "int.availability",
        Label.INTERVIEW,
        _p(r"\bavailability\s+for\s+(?:a|an)\s+(?:call|interview|chat)\b"),
        0.85,
    ),
    Rule(
        "int.pick_a_time",
        Label.INTERVIEW,
        _with_context(
            _APPLICATION_CONTEXT + "|interview",
            r"\b(?:pick|choose|select|book)\s+(?:a\s+|your\s+)?(?:time|slot|date)\b"
            r"|\bbook\s+(?:a|an|your)\s+(?:\d+[- ]?minutes?\s+)?(?:\w+\s+){0,2}"
            r"(?:conversation|call|chat|interview|session|meeting)\b",
        ),
        0.85,
    ),
    Rule(
        "int.love_to_chat",
        Label.INTERVIEW,
        _with_context(
            _APPLICATION_CONTEXT,
            r"\b(?:we'?d|we\s+would|i'?d|i\s+would)\s+(?:love|like)\s+to\s+(?:chat|talk|speak|meet|connect)\b",
        ),
        0.85,
    ),
    Rule(
        "int.move_you_forward",
        Label.INTERVIEW,
        _p(
            r"\bmove\s+you\s+(?:forward|to\s+the\s+next\s+(?:round|stage|step))\b"
            r"|\b(?:like|love|happy|pleased|excited)\s+to\s+move\s+(?:you\s+)?forward\b"
            r"|\bselected\s+to\s+move\s+forward\b"
        ),
        0.85,
    ),
    Rule(
        "int.share_availability",
        Label.INTERVIEW,
        _p(
            r"\b(?:share|send|provide|reply\s+with|let\s+(?:us|me)\s+know)\s+(?:us\s+|me\s+)?"
            r"(?:your|a\s+few|two|some)\s+(?:times?|availability|dates)\b"
            r"|\bwhat\s+does\s+your\s+availability\s+look\s+like\b"
        ),
        0.85,
    ),
    Rule(
        "int.interview_confirmation",
        Label.INTERVIEW,
        _p(
            r"\binterview\s+(?:confirmation|invitation|invite|request)\b"
            r"|\byour\s+interview\s+(?:is|has\s+been)\s+(?:confirmed|scheduled)\b"
            r"|\binvitation:[^\n]{0,100}\binterview\b|\btopic:[^\n]{0,80}\binterview\b"
        ),
        0.9,
    ),
    Rule(
        "int.scheduled_chat",
        Label.INTERVIEW,
        _p(r"\bconfirmed:[^\n]{0,60}\b(?:chat|call|screen)\b"),
        0.65,
    ),
    # Weak, context-free cues: never auto-apply (below the review threshold).
    Rule("int.onsite", Label.INTERVIEW, _p(r"\bon-?site\b"), 0.6),
    Rule("int.next_round", Label.INTERVIEW, _p(r"\bnext\s+round\b"), 0.6),
    Rule(
        "oa.hackerrank_invite",
        Label.ONLINE_ASSESSMENT,
        _p(_OA_DOMAINS),
        0.85,
        fields=("from_domain",),
    ),
    Rule("oa.online_assessment", Label.ONLINE_ASSESSMENT, _p(r"\bonline\s+assessment\b"), 0.85),
    Rule(
        "oa.coding_challenge",
        Label.ONLINE_ASSESSMENT,
        _p(
            r"\b(?:complete|take|your|the|this|a|an)\s+(?:(?!new\b)\w+\s+)?coding\s+challenge\b"
            r"(?!\s+(?:platform|site|website|app|tool|community))"
            r"|^coding\s+challenge\b"
        ),
        0.85,
    ),
    Rule(
        "oa.technical_assessment", Label.ONLINE_ASSESSMENT, _p(r"\btechnical\s+assessment\b"), 0.85
    ),
    Rule(
        "oa.complete_assessment",
        Label.ONLINE_ASSESSMENT,
        _with_context(
            _APPLICATION_CONTEXT,
            r"\b(?:complete|take)\s+(?:the|this|your|an?)\s+(?:\w+\s+)?assessment\b",
        ),
        0.85,
    ),
    Rule("oa.take_home", Label.ONLINE_ASSESSMENT, _p(r"\btake-?\s?home\b"), 0.8),
    Rule(
        "conf.received_application",
        Label.CONFIRMATION,
        _p(
            r"\b(?:received|got)\s+your\s+application\b"
            r"|\byour\s+application\s+(?:has\s+been\s+)?(?:received|submitted)\b"
        ),
        0.75,
    ),
    Rule(
        "conf.thank_you_applying",
        Label.CONFIRMATION,
        _p(r"\bthank\s+you\s+for\s+(?:applying|your\s+application)\b"),
        0.75,
    ),
    Rule(
        "conf.application_sent",
        Label.CONFIRMATION,
        _p(
            r"\bapplication\s+(?:was\s+|has\s+been\s+|is\s+)?(?:sent|submitted)\b"
            r"|\byour\b[^.!?]{0,60}\bapplication\s+(?:has\s+been\s+|was\s+)?received\b"
            r"|\bapplication\b[^.!?]{0,80}\b(?:is\s+)?now\s+under\s+review\b"
            r"|\bwe\s+have\s+your\s+application\b"
        ),
        0.75,
    ),
    Rule(
        "conf.successfully_applied",
        Label.CONFIRMATION,
        _p(r"\bsuccessfully\s+applied\b|\byou(?:'ve|\s+have)\s+applied\s+(?:to|for)\b"),
        0.75,
    ),
    Rule(
        "conf.thanks_applying",
        Label.CONFIRMATION,
        _p(r"\bthanks\s+for\s+(?:applying|your\s+application)\b"),
        0.75,
    ),
    Rule(
        "conf.well_review",
        Label.CONFIRMATION,
        _p(r"\bwe(?:\s+will|'ll)\s+(?:review|look\s+at)\s+your\s+application\b"),
        0.75,
    ),
    Rule(
        "conf.will_review",
        Label.CONFIRMATION,
        _p(r"\bwe\s+(?:will|'ll)\s+review\s+your\s+application\b"),
        0.75,
    ),
    Rule(
        "rec.came_across_profile",
        Label.RECRUITER_MESSAGE,
        _p(r"\bcame\s+across\s+your\s+(?:profile|resume|background)\b"),
        0.75,
    ),
    Rule("rec.reaching_out", Label.RECRUITER_MESSAGE, _p(r"\breaching\s+out\s+about\b"), 0.75),
    Rule("rec.open_to", Label.RECRUITER_MESSAGE, _p(r"\bwould\s+you\s+be\s+open\s+to\b"), 0.75),
    Rule("rec.interested_in", Label.RECRUITER_MESSAGE, _p(r"\bare\s+you\s+interested\s+in\b"), 0.6),
)


def needs_review(label: Label | None, confidence: float, threshold: float) -> bool:
    return label is None or confidence < threshold


_BOUNDARY = ".!?;\n"
_CONDITIONAL_LABELS = (
    Label.INTERVIEW,
    Label.OFFER,
    Label.ONLINE_ASSESSMENT,
    Label.REJECTION,
)
_BODY = "body"


def _sentence_bounds(text: str, pos: int) -> tuple[int, int]:
    start = max((text.rfind(ch, 0, pos) for ch in _BOUNDARY), default=-1) + 1
    ends = [i for ch in _BOUNDARY if (i := text.find(ch, pos)) != -1]
    return start, min(ends) if ends else len(text)


def _sentence_at(text: str, pos: int) -> str:
    start, end = _sentence_bounds(text, pos)
    return text[start:end]


def _hypothetical(text: str, match: re.Match[str]) -> bool:
    """The match sits in a sentence that makes it conditional, before or after it ("if selected,
    we will ..." and "we will ... if you are selected")."""
    return _HYPOTHETICAL.search(_sentence_at(text, max(match.end() - 1, 0))) is not None


def _live_match(rule: Rule, text: str) -> re.Match[str] | None:
    """First match of the rule that is not conditional wording."""
    for match in rule.pattern.finditer(text):
        if rule.label in _CONDITIONAL_LABELS and _hypothetical(text, match):
            continue
        return match
    return None


def _matches(rule: Rule, texts: dict[str, str]) -> bool:
    return any(_live_match(rule, texts[f]) for f in rule.fields)


_CONTRAST_OPENER = re.compile(r"\s*(?:but|however|that\s+said|although|though|still)\b")


def _contrast_in(field_name: str, text: str, match: re.Match[str]) -> bool:
    """Contrast anywhere in a short field; in a body only in the matching sentence, or in the next
    one when that opens with a contrast word ("But we would like to interview you for ...")."""
    if field_name != _BODY:
        return _CONTRAST.search(text) is not None
    start, end = _sentence_bounds(text, max(match.end() - 1, 0))
    scope = text[start:end]
    if end + 1 < len(text):
        following = _sentence_at(text, end + 1)
        if _CONTRAST_OPENER.match(following):
            scope += " " + following
    return _CONTRAST.search(scope) is not None


def _confidence(rule: Rule, texts: dict[str, str]) -> float:
    """Rejections drop below the review threshold when the matching field has a contrast signal."""
    if rule.label is Label.REJECTION:
        for f in rule.fields:
            match = _live_match(rule, texts[f])
            if match and _contrast_in(f, texts[f], match):
                return min(rule.confidence, VETOED_CONFIDENCE)
    return rule.confidence


# Negative or regret wording in the same sentence turns an interview/offer match into noise.
_NEGATIVE_CUE = re.compile(
    r"\bregret|\bunfortunately\b|\bunable\b|\bnot\s+able\b|\bdecided\s+against\b"
    r"|\b(?:chose|chosen|choose)\s+not\s+to\b|\bno\s+longer\b|\bwill\s+not\b|\bwon't\b"
    r"|\bcannot\b|\bcan't\b|\bdeclin(?:e|ed|ing)\b"
    r"|\bnot\s+(?:be|been|move|moving|advance|advancing|proceed|proceeding)\b",
    re.IGNORECASE,
)
_INTERVIEW_OFFER = (Label.INTERVIEW, Label.OFFER)
# A "confirmation" next to wording that sounds like a rejection (one no rejection rule matched) is
# not trusted: it is more likely an unrecognised rejection than a confirmation.
_REJECTIONISH = re.compile(
    r"\bunfortunately\b|\bregret\b|\b(?:other|another|different)\s+(?:candidates?|applicants?)\b"
    r"|\bnot\s+(?:be\s+)?(?:selected|successful|moving|proceeding|advancing|continuing)\b"
    r"|\bdecided\s+(?:not|to\s+(?:pursue|proceed|move|go))\b|\bno\s+longer\b"
    r"|\bunable\b|\bnot\s+able\b|\bcannot\b|\bcan't\b|\bwon't\b|\bwill\s+not\b"
    r"|\bnot\s+(?:a\s+)?(?:match|fit)\b|\bdeclin(?:e|ed|ing)\b|\bfilled\b|\bwent\s+with\b"
    r"|\bpass\s+on\b"
)


def _unconditional(text: str) -> str:
    """The text without its conditional sentences ("if we are unable to ..., we will email you")."""
    sentences = re.split(r"(?<=[.!?;\n])", text)
    return " ".join(x for x in sentences if not _HYPOTHETICAL.search(x))


def _rejectionish(rule: Rule, texts: dict[str, str]) -> bool:
    """Wording like a rejection, ignoring conditional sentences and phrasing."""
    return rule.label is Label.CONFIRMATION and any(
        _REJECTIONISH.search(re.sub(_CONDITIONAL, " ", _unconditional(texts[f])))
        for f in ("subject", "snippet", "body")
    )


def _negated(rule: Rule, texts: dict[str, str]) -> bool:
    """True when the sentence holding the rule's match carries a negative cue."""
    for field_name in rule.fields:
        match = _live_match(rule, texts[field_name])
        if match and _NEGATIVE_CUE.search(_sentence_at(texts[field_name], max(match.end() - 1, 0))):
            return True
    return False


class RulesProvider:
    def __init__(self, threshold: float | None = None) -> None:
        value = get_settings().classifier_review_threshold if threshold is None else threshold
        if not 0 <= value <= 1:
            raise ValueError("threshold must be between 0 and 1")
        self._threshold = value

    def classify(self, inp: ClassificationInput) -> ClassificationResult:
        texts = {
            "from_domain": normalize_text(inp.from_domain).lower(),
            "subject": normalize_text(inp.subject).lower(),
            "snippet": normalize_text(inp.snippet).lower(),
            "body": normalize_text(inp.body).lower(),
        }
        hits = [(r, _confidence(r, texts)) for r in RULES if _matches(r, texts)]
        negated = [h for h in hits if h[0].label in _INTERVIEW_OFFER and _negated(h[0], texts)]
        hits = [h for h in hits if h not in negated and not _rejectionish(h[0], texts)]
        strong = [(r, c) for r, c in hits if c >= STRONG]
        has_rejection = any(r.label is Label.REJECTION for r, _ in strong)
        if negated and not any(r.label is Label.REJECTION and c >= SPECIFIC for r, c in strong):
            return self._undecided(negated[0][0].id)
        if not hits:
            return self._undecided(None)
        if has_rejection and any(r.label in _INTERVIEW_OFFER for r, _ in hits):
            return self._undecided(strong[0][0].id)
        if strong:
            if any(r.label != strong[0][0].label for r, _ in strong):
                return self._undecided(strong[0][0].id)
            return self._decided(*strong[0])
        return self._decided(*hits[0])

    def _decided(self, rule: Rule, confidence: float) -> ClassificationResult:
        return ClassificationResult(
            label=rule.label,
            confidence=confidence,
            method="rules",
            rule_id=rule.id,
            needs_review=needs_review(rule.label, confidence, self._threshold),
        )

    def _undecided(self, rule_id: str | None) -> ClassificationResult:
        return ClassificationResult(
            label=None, confidence=0.0, method="rules", rule_id=rule_id, needs_review=True
        )
