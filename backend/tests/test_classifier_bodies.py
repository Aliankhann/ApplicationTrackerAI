# ruff: noqa: E501
"""Phase 2: the classifier reads a cleaned body window; every guard still holds."""

import time

import pytest

from app.providers.classifier.rules import RulesProvider
from app.providers.classifier.types import ClassificationInput, Label

RULES = RulesProvider()
ATS = "no-reply.example"


def classify(subject: str = "", snippet: str = "", body: str = "", domain: str = ATS):  # type: ignore[no-untyped-def]
    return RULES.classify(ClassificationInput(domain, subject, snippet, body))


def decided(result) -> Label | None:  # type: ignore[no-untyped-def]
    return None if result.needs_review else result.label


def test_ac_the_key_sentence_after_the_snippet_window_decides() -> None:
    body = (
        "Hi Sam,\n\n"
        + "Thanks for your time. " * 12
        + "We will not be moving forward with your application."
    )
    assert (
        decided(classify("Update", "Hi Sam, Thanks for your time. Thanks", body)) == Label.REJECTION
    )


def test_ac_snippet_only_input_still_works_without_a_body() -> None:
    assert decided(classify("Update", "We would like to schedule an interview")) == Label.INTERVIEW


@pytest.mark.parametrize(
    ("body", "label"),
    [
        ("Your application was sent to Acme.\nSoftware Engineer Intern", Label.CONFIRMATION),
        ("Thanks for applying to the role!", Label.CONFIRMATION),
        ("You've successfully applied to Intern at Initech.", Label.CONFIRMATION),
        ("We'll review your application and get back to you.", Label.CONFIRMATION),
        (
            "Please pick a time that works for you using the link. We got your application.",
            Label.INTERVIEW,
        ),
        ("We'd love to chat about your application. Book a 30 minute call.", Label.INTERVIEW),
        ("We would like to move you to the next round.", Label.INTERVIEW),
        ("Please share your availability for a call next week.", Label.INTERVIEW),
        ("Invitation: Acme Interview @ Tue Dec 2, 2pm", Label.INTERVIEW),
        ("Topic: Globex Final Interview\nTime: Dec 3", Label.INTERVIEW),
        ("We would like to offer you the Backend Intern position at Hooli.", Label.OFFER),
        (
            "As the next step in your application, please complete the assessment.",
            Label.ONLINE_ASSESSMENT,
        ),
        (
            "We have chosen to proceed with applicants whose experience aligns better.",
            Label.REJECTION,
        ),
        (
            "At this point we are not able to offer you the Avionics Software Intern position.",
            Label.REJECTION,
        ),
        ("Your application was not successful this time.", Label.REJECTION),
    ],
)
def test_ac_the_rule_families_from_the_diagnosis(body: str, label: Label) -> None:
    assert decided(classify("Update", "", body)) == label


def test_ac_footer_text_cannot_make_a_confirmation_look_like_a_job_alert() -> None:
    result = classify(
        "Indeed Application: QA Intern", "Application submitted. Manage your Indeed job alerts"
    )
    assert decided(result) == Label.CONFIRMATION


def test_ac_a_real_job_alert_digest_is_still_irrelevant() -> None:
    assert decided(classify("Your job alert: 12 new jobs for you")) == Label.IRRELEVANT
    assert (
        decided(classify("Notification", "Job alert from Acme: 8 matching roles posted."))
        == Label.IRRELEVANT
    )


def test_ac_conditional_wording_in_a_body_is_not_an_interview() -> None:
    body = "We have received your application. If selected, a recruiter will contact you to schedule an interview."
    assert decided(classify("Thanks", "", body)) == Label.CONFIRMATION


def test_ac_may_be_asked_to_complete_an_assessment_is_not_an_assessment_invite() -> None:
    body = "Your application was received. You may be asked to complete an online assessment."
    assert decided(classify("Thanks", "", body)) == Label.CONFIRMATION


def test_ac_not_able_to_respond_to_everyone_is_not_a_rejection() -> None:
    body = "We received your application. Unfortunately, we are unable to respond to every application individually."
    assert decided(classify("Thanks", "", body)) != Label.REJECTION


def test_ac_conditional_rejection_wording_is_not_a_rejection() -> None:
    body = "Thank you for applying. If you are not selected, we will let you know."
    assert decided(classify("Thanks", "", body)) == Label.CONFIRMATION


def test_ac_a_rejection_with_contrast_in_its_sentence_still_needs_review() -> None:
    body = "We will not be moving forward with your application, but we have another opening."
    result = classify("Update", "", body)
    assert result.label == Label.REJECTION and result.needs_review


def test_ac_a_contrast_opening_the_next_sentence_also_vetoes_the_rejection() -> None:
    body = (
        "We will not be moving forward with your application. However, another role fits you well."
    )
    assert classify("Update", "", body).needs_review


def test_ac_a_later_unrelated_sentence_does_not_veto_a_rejection() -> None:
    body = (
        "We regret to inform you that your application was unsuccessful. "
        "We encourage you to apply to other openings in the future."
    )
    assert decided(classify("Update", "", body)) == Label.REJECTION


def test_ac_an_unrecognised_rejection_is_not_trusted_as_a_confirmation() -> None:
    body = "Thank you for applying. Your profile is not a match for what we need right now."
    assert decided(classify("Update", "", body)) is None


def test_ac_negated_offer_wording_in_a_body_is_not_an_offer() -> None:
    body = "We will not be extending an offer for the Backend Intern position."
    assert decided(classify("Update", "", body)) != Label.OFFER


def test_ac_a_coding_challenge_newsletter_is_not_an_assessment() -> None:
    body = "Top stories: hiring trends and a new coding challenge platform for practice."
    assert decided(classify("Weekly digest", "", body)) is None


def test_ac_a_weak_scheduling_confirmation_is_only_a_suggestion() -> None:
    result = classify("Confirmed: 30 Minute Chat with Dana Whitfield - Globex")
    assert result.label == Label.INTERVIEW and result.needs_review


def test_ac_classification_stays_fast_on_hostile_bodies() -> None:
    hostile = ("We will not be " * 400) + (". " * 600) + ("unfortunately " * 300)
    start = time.perf_counter()
    classify("Update", "x", hostile)
    classify("Update", "x", "a" * 8000)
    assert time.perf_counter() - start < 2.0
