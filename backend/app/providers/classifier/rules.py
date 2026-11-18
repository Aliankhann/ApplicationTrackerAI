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
VETOED_CONFIDENCE = 0.5
_FIELDS = ("subject", "snippet")

# Conditional phrasing ("if you are not selected") must never read as a rejection.
_CONDITIONAL = r"\bif\s+(?:you|we)\s+(?:are\s+|were\s+|do\s+)?not\b|\bshould\s+you\s+not\b"
# Contrast, continuation, or quoting in the same field demotes a rejection to "needs review".
_CONTRAST = re.compile(
    r"\bbut\b|\bhowever\b|\b(?:another|other)\s+(?:role|opening|position|team|cohort)s?\b"
    r"|\bwould\s+like\s+to\s+(?:interview|invite|consider|speak|chat)\b"
    r"|\blove\s+to\s+consider\b|\bstill\s+under\s+consideration\b|\bfor\s+20\d\d\b"
    r"|\bnewsletter\b|\bunsubscribe\b|\bwebinar\b"
)
_RESCINDED = r"\brescind(?:ed|ing)?\b|\bwithdr(?:aw|awn|ew)\b|\brevok(?:e|ed)\b"

_S = r"[^.!?;\n]"  # one sentence
_SENT = r"(?:\A|(?<=[.!?;\n]))"
_APP = r"application|candidacy|candidature|role|position|candidates?|applicants?"
_SUBJ = r"(?:we|we're|we are|we've|we have|we will|we won't|our team|the team|the hiring team)"
_NOT_FORWARD = r"(?:not|won't|wont)\s+(?:be\s+)?(?:moving|move|proceeding|proceed)\s+forward"
_CANDIDATES = r"(?:other|another)\s+(?:candidates?|applicants?)"


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


def _offer(body: str) -> re.Pattern[str]:
    interview = r"(?!\s+(?:to\s+)?(?:an?\s+|the\s+)?(?:interview|call|chat|opportunity\s+to)\b)"
    return _guarded(_RESCINDED, rf"(?:{body}){interview}")


_OA_DOMAINS = r"(?:^|\.)(?:hackerrank|hackerrankforwork|codesignal|codility)\.com$"

RULES: tuple[Rule, ...] = (
    Rule(
        "irr.job_alert_digest",
        Label.IRRELEVANT,
        _p(
            r"\bnew\s+jobs?\s+for\s+you\b|\bjobs?\s+you\s+may\s+be\s+interested\s+in\b|\bjob\s+alerts?\b"
        ),
        0.9,
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
            r"\b(?:won't|will\s+not|cannot|can't|unable|not\s+able)\s+(?:be\s+able\s+)?to\s+offer\s+you"
            r"\s+(?:the|a|an)\s+(?:role|position|internship|job)\b"
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
    Rule("int.onsite", Label.INTERVIEW, _p(r"\bon-?site\b"), 0.75),
    Rule("int.next_round", Label.INTERVIEW, _p(r"\bnext\s+round\b"), 0.75),
    Rule(
        "oa.hackerrank_invite",
        Label.ONLINE_ASSESSMENT,
        _p(_OA_DOMAINS),
        0.85,
        fields=("from_domain",),
    ),
    Rule("oa.online_assessment", Label.ONLINE_ASSESSMENT, _p(r"\bonline\s+assessment\b"), 0.85),
    Rule("oa.coding_challenge", Label.ONLINE_ASSESSMENT, _p(r"\bcoding\s+challenge\b"), 0.85),
    Rule(
        "oa.technical_assessment", Label.ONLINE_ASSESSMENT, _p(r"\btechnical\s+assessment\b"), 0.85
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


def _matches(rule: Rule, texts: dict[str, str]) -> bool:
    return any(rule.pattern.search(texts[f]) for f in rule.fields)


def _confidence(rule: Rule, texts: dict[str, str]) -> float:
    """Rejections drop below the review threshold when the matching field has a contrast signal."""
    if rule.label is Label.REJECTION and any(
        rule.pattern.search(texts[f]) and _CONTRAST.search(texts[f]) for f in rule.fields
    ):
        return min(rule.confidence, VETOED_CONFIDENCE)
    return rule.confidence


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
        }
        hits = [(r, _confidence(r, texts)) for r in RULES if _matches(r, texts)]
        if not hits:
            return self._undecided(None)
        strong = [(r, c) for r, c in hits if c >= STRONG]
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
