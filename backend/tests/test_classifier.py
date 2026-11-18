"""Rules engine, provider interface, cache and review threshold (US-41, US-44, US-47)."""

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.providers.classifier.base import ClassifierProvider
from app.providers.classifier.cache import CachingProvider
from app.providers.classifier.rules import RULES, RulesProvider
from app.providers.classifier.types import ClassificationInput, ClassificationResult, Label
from app.services.classification import ApplicationStatus, apply_result

Case = tuple[str, str, str]  # from_domain, subject, snippet
JOB = "careers.example.com"

# rule id -> (positive, negative), all synthetic
EXAMPLES: dict[str, tuple[Case, Case]] = {
    "irr.job_alert_digest": ((JOB, "New jobs for you", ""), (JOB, "Your new job", "")),
    "rej.not_moving_forward": (
        (JOB, "Update", "We will not be moving forward with your application"),
        (JOB, "Update", "We are moving forward with your application"),
    ),
    "rej.pursue_other_candidates": (
        (JOB, "Update", "We have decided to pursue other candidates"),
        (JOB, "Update", "We pursue our goals"),
    ),
    "rej.position_filled": (
        (JOB, "Update", "The position has been filled"),
        (JOB, "Update", "The position is open"),
    ),
    "rej.regret_to_inform": (
        (JOB, "Update", "We regret to inform you that your application failed"),
        (JOB, "Update", "We regret to inform you our office is closed"),
    ),
    "rej.unfortunately_not": (
        (JOB, "Update", "Unfortunately, we are unable to move forward with your application"),
        (JOB, "Update", "Unfortunately the office is closed today"),
    ),
    "rej.no_longer_considered": (
        (JOB, "Update", "You are no longer under consideration"),
        (JOB, "Update", "You are under consideration"),
    ),
    "rej.ne_pas_donner_suite": (
        (JOB, "Candidature", "Nous ne pouvons pas donner suite a votre candidature"),
        (JOB, "Candidature", "Nous allons donner suite"),
    ),
    "rej.not_proceeding": (
        (JOB, "Update", "We will not be proceeding with your application"),
        (JOB, "Update", "We will not be proceeding with the event"),
    ),
    "rej.decided_not_to_proceed": (
        (JOB, "Update", "We've decided not to proceed with your application"),
        (JOB, "Update", "We've decided to proceed"),
    ),
    "rej.forward_with_other": (
        (JOB, "Update", "We are moving forward with other candidates"),
        (JOB, "Update", "We are moving forward with your candidacy"),
    ),
    "rej.selected_other": (
        (JOB, "Update", "We selected other applicants"),
        (JOB, "Update", "We selected your application"),
    ),
    "rej.careful_consideration": (
        (JOB, "Update", "After careful consideration, we chose another candidate"),
        (JOB, "Update", "After careful consideration, we chose you"),
    ),
    "rej.application_unsuccessful": (
        (JOB, "Update", "Your application was unsuccessful"),
        (JOB, "Update", "Your application was successful"),
    ),
    "rej.unable_to_offer": (
        (JOB, "Update", "We won't be able to offer you the role"),
        (JOB, "Update", "We are able to offer you the role"),
    ),
    "int.interview_you": (
        (JOB, "Next", "We would like to interview you"),
        (JOB, "Next", "The interviewer is out"),
    ),
    "int.offer_interview": (
        (JOB, "Next", "We would like to offer you an interview"),
        (JOB, "Next", "We would like to offer you a discount"),
    ),
    "off.pleased_to_offer": (
        (JOB, "Good news", "We are pleased to offer you the role"),
        (JOB, "Good news", "We are pleased to offer you an interview"),
    ),
    "off.offer_letter": (
        (JOB, "Your offer letter", ""),
        (JOB, "Special offer", "Save on gear"),
    ),
    "int.schedule_interview": (
        (JOB, "Next", "Please schedule your interview"),
        (JOB, "Next", "Please schedule your flight"),
    ),
    "int.invite_interview": (
        (JOB, "Next", "We would like to invite you to an interview"),
        (JOB, "Next", "We would like to invite you to a webinar"),
    ),
    "int.phone_screen": (
        (JOB, "Phone screen", ""),
        (JOB, "Phone", "screen your calls"),
    ),
    "int.superday": ((JOB, "Superday details", ""), (JOB, "Super day sale", "")),
    "int.hirevue": ((JOB, "Your HireVue link", ""), (JOB, "Your video link", "")),
    "int.availability": (
        (JOB, "Next", "Share your availability for a call"),
        (JOB, "Next", "Share your availability on Slack"),
    ),
    "int.onsite": ((JOB, "Onsite details", ""), (JOB, "Remote details", "")),
    "int.next_round": ((JOB, "Next round", ""), (JOB, "Next week", "")),
    "oa.hackerrank_invite": (
        ("mail.hackerrank.com", "Hello", ""),
        ("nothackerrank.com", "Hello", ""),
    ),
    "oa.online_assessment": ((JOB, "Online assessment", ""), (JOB, "Online store", "")),
    "oa.coding_challenge": ((JOB, "Your coding challenge", ""), (JOB, "Your coding class", "")),
    "oa.technical_assessment": (
        (JOB, "Technical assessment", ""),
        (JOB, "Technical blog", ""),
    ),
    "oa.take_home": ((JOB, "Take-home project", ""), (JOB, "Take a break", "")),
    "conf.received_application": (
        (JOB, "Hi", "We have received your application"),
        (JOB, "Hi", "We have received your package"),
    ),
    "conf.thank_you_applying": (
        (JOB, "Thank you for applying", ""),
        (JOB, "Thank you for visiting", ""),
    ),
    "conf.will_review": (
        (JOB, "Hi", "We will review your application"),
        (JOB, "Hi", "We will review your invoice"),
    ),
    "rec.came_across_profile": (
        (JOB, "Hi", "I came across your profile"),
        (JOB, "Hi", "I came across a bug"),
    ),
    "rec.reaching_out": ((JOB, "Hi", "Reaching out about a role"), (JOB, "Hi", "Reaching a goal")),
    "rec.open_to": ((JOB, "Hi", "Would you be open to a chat"), (JOB, "Hi", "Be open")),
    "rec.interested_in": (
        (JOB, "Hi", "Are you interested in joining us"),
        (JOB, "Hi", "I am interested in joining"),
    ),
}


def classify(case: Case) -> ClassificationResult:
    return RulesProvider(threshold=0.7).classify(ClassificationInput(*case))


# AC1
def test_us41_ac1_rule_ids_unique_and_valid() -> None:
    ids = [r.id for r in RULES]
    assert len(ids) == len(set(ids))
    assert all(r.label in set(Label) and 0 < r.confidence <= 1 for r in RULES)


def test_us41_ac1_every_rule_has_examples() -> None:
    assert {r.id for r in RULES} == set(EXAMPLES)


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.id)
def test_us41_ac1_positive_and_negative_examples(rule: object) -> None:
    from app.providers.classifier.rules import Rule, _matches
    from app.text import normalize_text

    assert isinstance(rule, Rule)
    positive, negative = EXAMPLES[rule.id]

    def texts(case: Case) -> dict[str, str]:
        d, s, n = (normalize_text(x).lower() for x in case)
        return {"from_domain": d, "subject": s, "snippet": n}

    assert _matches(rule, texts(positive))
    assert not _matches(rule, texts(negative))


# AC2
@pytest.mark.parametrize(
    ("snippet", "label"),
    [
        (
            "Thank you for applying. Unfortunately we will not be moving forward",
            Label.REJECTION,
        ),
        ("Thank you for applying. We will review your application", Label.CONFIRMATION),
        (
            "We received your application. If you are not selected, we will let you know",
            Label.CONFIRMATION,
        ),
        ("Thank you for applying. Should you not be selected we will email", Label.CONFIRMATION),
        ("Unfortunately the office is closed", None),
    ],
)
def test_us41_ac2_rejection_vs_confirmation(snippet: str, label: Label | None) -> None:
    assert classify((JOB, "Your application", snippet)).label == label


def test_us41_ac2_accents_are_normalized() -> None:
    result = classify((JOB, "Candidature", "Nous ne pouvons pas donner suite à votre candidature"))
    assert result.label == Label.REJECTION


# AC3
@pytest.mark.parametrize(
    "text", ["Special offer just for you", "Get 20% off today", "Offers inside"]
)
def test_us41_ac3_promo_never_offer(text: str) -> None:
    assert classify((JOB, text, "")).label != Label.OFFER


def test_us41_ac3_job_alert_is_irrelevant() -> None:
    result = classify((JOB, "Job alert: 5 new jobs for you", ""))
    assert (result.label, result.needs_review) == (Label.IRRELEVANT, False)


# AC4
def test_us41_ac4_conflicting_strong_matches() -> None:
    result = classify((JOB, "Online assessment", "Please schedule your interview"))
    assert result.label is None
    assert result.needs_review
    assert result.confidence == 0
    assert result.rule_id == "int.schedule_interview"


# AC5
def test_us41_ac5_no_match() -> None:
    result = classify((JOB, "Hello", "Nothing relevant"))
    assert (result.label, result.needs_review, result.method, result.rule_id) == (
        None,
        True,
        "rules",
        None,
    )


def test_us41_strong_match_records_rule_and_method() -> None:
    result = classify((JOB, "Update", "We will not be moving forward with your application"))
    assert (result.rule_id, result.method) == ("rej.not_moving_forward", "rules")


# AC6
def test_us44_ac6_providers_satisfy_interface() -> None:
    rules: ClassifierProvider = RulesProvider()
    cached: ClassifierProvider = CachingProvider(rules)
    assert cached.classify(ClassificationInput(JOB, "Hello", "")).label is None


# AC7
class CountingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def classify(self, inp: ClassificationInput) -> ClassificationResult:
        self.calls += 1
        return ClassificationResult(Label.OFFER, 0.9, "rules", "x", False)


def test_us44_ac7_identical_input_hits_cache_different_snippet_misses() -> None:
    inner = CountingProvider()
    cache = CachingProvider(inner)
    cache.classify(ClassificationInput("a.com", "s", "one"))
    cache.classify(ClassificationInput("a.com", "s", "one"))
    assert (inner.calls, cache.hits, cache.misses) == (1, 1, 1)
    cache.classify(ClassificationInput("a.com", "s", "two"))
    assert (inner.calls, cache.hits, cache.misses) == (2, 1, 2)


def test_us44_cache_evicts_least_recently_used() -> None:
    inner = CountingProvider()
    cache = CachingProvider(inner, maxsize=1)
    for snippet in ("one", "two", "one"):
        cache.classify(ClassificationInput("a.com", "s", snippet))
    assert inner.calls == 3


# AC8
def test_us47_ac8_low_confidence_sets_needs_review() -> None:
    weak = classify((JOB, "Hi", "Are you interested in joining us"))
    assert weak.label == Label.RECRUITER_MESSAGE
    assert weak.needs_review
    assert not classify((JOB, "Hi", "I came across your profile")).needs_review
    assert (
        RulesProvider(threshold=0.8)
        .classify(ClassificationInput(JOB, "Hi", "I came across your profile"))
        .needs_review
    )


@pytest.mark.parametrize(
    ("label", "status"),
    [
        (Label.CONFIRMATION, ApplicationStatus.APPLIED),
        (Label.ONLINE_ASSESSMENT, ApplicationStatus.ONLINE_ASSESSMENT),
        (Label.INTERVIEW, ApplicationStatus.INTERVIEW),
        (Label.OFFER, ApplicationStatus.OFFER),
        (Label.REJECTION, ApplicationStatus.REJECTED),
        (Label.IRRELEVANT, None),
        (Label.RECRUITER_MESSAGE, None),
        (None, None),
    ],
)
def test_us47_ac8_apply_result_mapping(
    label: Label | None, status: ApplicationStatus | None
) -> None:
    result = ClassificationResult(label, 0.9, "rules", "x", False)
    assert apply_result(ApplicationStatus.APPLIED, result) == status


def test_us47_ac8_apply_result_ignores_needs_review() -> None:
    result = ClassificationResult(Label.REJECTION, 0.5, "rules", "x", True)
    assert apply_result(ApplicationStatus.INTERVIEW, result) is None


# AC9
@pytest.mark.parametrize("value", [-0.1, 1.5])
def test_us47_ac9_threshold_out_of_range_raises(value: float) -> None:
    with pytest.raises(ValidationError):
        Settings(classifier_review_threshold=value)


def test_us47_ac9_threshold_default() -> None:
    assert Settings().classifier_review_threshold == 0.7
