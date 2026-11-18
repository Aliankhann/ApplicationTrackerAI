"""Adversarial rejection tests (synthetic text): a wrong rejection is the costliest error."""

import time

import pytest

from app.providers.classifier.cache import cache_key
from app.providers.classifier.rules import RulesProvider
from app.providers.classifier.types import ClassificationInput, Label

# (subject, snippet, is_rejection)
CASES: list[tuple[str, str, bool]] = [
    ("Update", "We regret to inform you that our office will be closed on Friday", False),
    ("Interview", "Unfortunately the interview time no longer works, can we reschedule?", False),
    ("Status", "Your application has not been reviewed yet", False),
    ("Visa", "We are not able to sponsor visas, but you are still under consideration", False),
    (
        "2026",
        "We will not be moving forward with the 2025 cohort "
        "but would like to interview you for 2026",
        False,
    ),
    (
        "Role",
        "The position has been filled; we have another opening and would like to interview you",
        False,
    ),
    (
        "Role",
        "You are no longer under consideration for the Software role, "
        "but we'd love to consider you for Data",
        False,
    ),
    ("Reschedule", "Unfortunately I cannot make Tuesday, can we move our call?", False),
    (
        "Fwd: Update",
        "---- Forwarded ---- We regret to inform you that we will not be moving forward",
        True,
    ),
    ("Hello", "Unfortunately. Not all slots are available, please pick another", False),
    ("We will not be moving forward with your application", "", True),
    ("Update", "We will not be moving forward with your application", True),
    ("Update", "We have decided to move forward with other candidates", True),
    ("Update", "We won't be moving forward with your candidacy", True),
    ("Update", "We have filled the role", True),
    ("Update", "After careful consideration, we selected other applicants", True),
    ("Update", "We've decided not to proceed with your application", True),
    ("Update", "We have decided not to move forward", True),
    ("Update", "Unfortunately, we are unable to offer you a position at this time", True),
    ("Update", "We regret to inform you that we are unable to proceed with your application", True),
    ("Update", "Your application was unsuccessful", True),
    ("Update", "We will not be proceeding with your application", True),
    ("Update", "Thanks for applying. Unfortunately we won't be moving forward.", True),
    ("Update", "We're sorry to say we won't be able to offer you the role", True),
    ("Update", "We are moving forward with other candidates", True),
    ("Update", "We chose to pursue other candidates whose experience more closely matches", True),
    ("Update", "Not moving forward with your application", True),
    ("Offer", "Unfortunately we cannot wait: please accept your offer letter by Friday", False),
    ("Interview", "We would like to offer you an interview", False),
    ("Update", "If we are not able to move forward we will let you know", False),
    (
        "Update",
        "Unfortunately the recruiter is out of office; "
        "we will not be moving forward without your availability",
        False,
    ),
    ("Update", "Please do not move forward with the assessment until you get the link", False),
    ("Update", "We have not yet decided whether we will be moving forward", False),
    ("Update", "We'll let you know if we are moving forward", False),
    # more realistic negatives
    ("Interview", "Unfortunately I need to reschedule our interview to Thursday", False),
    ("Auto-reply", "I am out of office until Monday and unfortunately not able to reply", False),
    (
        "Visa",
        "Unfortunately we are unable to sponsor, but your application is still under consideration",
        False,
    ),
    ("Status", "Your application is not reviewed yet, we will not be able to reply today", False),
    (
        "Weekly newsletter",
        "Newsletter: candidates told us we will not be moving forward "
        "with your application is the worst line",
        False,
    ),
    ("Update", "Your offer was rescinded", False),
    ("Next", "We would like to offer you the opportunity to interview", False),
    ("Update", "Don't worry if you are not selected, we'll let you know", False),
    ("Hi", "Thank you for applying, we will review your application", False),
    ("Sale", "Special offer: 20% off, unfortunately only today", False),
    # more positives
    ("Update", "We regret to inform you that we have decided not to proceed", True),
    (
        "Update",
        "Unfortunately, we will not be moving forward with your application at this time",
        True,
    ),
    ("Update", "Your candidacy was unsuccessful", True),
    ("Candidature", "Nous ne pouvons pas donner suite à votre candidature", True),
    (
        "Update",
        "After careful consideration, we have chosen to move forward with other candidates",
        True,
    ),
    (
        "Update",
        "Thank you for applying. Unfortunately we will not be moving forward with your application",
        True,
    ),
]


def _is_rejection(subject: str, snippet: str) -> bool:
    result = RulesProvider(threshold=0.7).classify(
        ClassificationInput("acme.com", subject, snippet)
    )
    return result.label is Label.REJECTION and not result.needs_review


@pytest.mark.parametrize(("subject", "snippet", "expected"), CASES)
def test_non_rejections_are_never_rejected(subject: str, snippet: str, expected: bool) -> None:
    if not expected:
        assert not _is_rejection(subject, snippet)


def test_rejection_precision_and_recall_gate() -> None:
    results = [(_is_rejection(s, n), exp) for s, n, exp in CASES]
    tp = sum(1 for got, exp in results if got and exp)
    fp = sum(1 for got, exp in results if got and not exp)
    fn = sum(1 for got, exp in results if not got and exp)
    precision = tp / (tp + fp)
    recall = tp / (tp + fn)
    assert precision >= 0.95, f"precision={precision:.2f} fp={fp}"
    assert recall >= 0.80, f"recall={recall:.2f} fn={fn}"


@pytest.mark.parametrize(
    ("subject", "snippet", "label"),
    [
        ("Next", "We would like to offer you an interview", Label.INTERVIEW),
        ("Next", "We are pleased to offer you an interview", Label.INTERVIEW),
        ("Next", "We would like to interview you for the role", Label.INTERVIEW),
    ],
)
def test_interview_not_offer(subject: str, snippet: str, label: Label) -> None:
    result = RulesProvider(threshold=0.7).classify(
        ClassificationInput("acme.com", subject, snippet)
    )
    assert result.label is label


def test_contrast_demotes_rejection_to_review() -> None:
    inp = ClassificationInput("a.com", "Update", "We regret to inform you, but another role fits")
    result = RulesProvider(threshold=0.7).classify(inp)
    assert result.label is Label.REJECTION
    assert result.needs_review


def test_threshold_validated_in_constructor() -> None:
    with pytest.raises(ValueError):
        RulesProvider(threshold=1.5)


def test_pathological_inputs_are_fast() -> None:
    provider = RulesProvider(threshold=0.7)
    bodies = [
        "unfortunately " * 8000,
        "unfortunately " + "a " * 50000,
        " " * 100000,
        "if " * 40000,
        "ne " * 40000 + "pas",
        "regret " * 15000,
        "we " * 30000,
        "a. " * 30000,
    ]
    for body in bodies:
        start = time.perf_counter()
        provider.classify(ClassificationInput("a.com", body, body))
        assert time.perf_counter() - start <= 1


def test_cache_key_ambiguity() -> None:
    a = cache_key(ClassificationInput("a", "b\x00c", "d"))
    b = cache_key(ClassificationInput("a", "b", "c\x00d"))
    assert a != b
