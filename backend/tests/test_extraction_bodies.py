# ruff: noqa: E501
"""Phase 4: company and role from the sender, subject, snippet and the cleaned body."""

import time

import pytest

from app.services.extraction import extract

GH = "no-reply@us.greenhouse-mail.io"


def got(address: str, name: str, subject: str, snippet: str = "", body: str = ""):  # type: ignore[no-untyped-def]
    found = extract(address, name, subject, snippet, body)
    return found.company, found.role


@pytest.mark.parametrize(
    "name", ["Pied Piper", "Stark Dynamics", "Massive Dynamic", "Tailspin Toys"]
)
def test_ac_an_ats_display_name_that_looks_like_a_person_is_trusted(name: str) -> None:
    assert extract(GH, name, "Update", "Hi Sam").company == name


def test_ac_an_ats_display_name_is_still_rejected_for_vendor_and_generic_words() -> None:
    for name in ("Greenhouse", "No Reply", "Workday Careers", "Careers", "Notifications"):
        assert extract(GH, name, "Update", "Hi").company is None


def test_ac_a_person_sent_via_the_ats_is_not_the_company() -> None:
    assert extract(GH, "Dana Whitfield via Greenhouse", "Update", "Hi").company is None
    assert extract("a@gmail.com", "Dana Whitfield", "Update", "Hi").company is None


def test_ac_myworkday_sender_names_the_tenant() -> None:
    found = extract("acme@myworkday.com", "", "Thank you for applying", "Hi Sam")
    assert (found.company, found.company_source) == ("Acme", "domain")


def test_ac_the_tenant_is_read_from_a_careers_link_in_the_body() -> None:
    body = (
        "Review the posting: https://zeta.wd5.myworkdayjobs.com/en-US/Careers/job/Remote/Intern_R1"
    )
    assert extract("no-reply@myworkday.com", "", "Update", "Hi", body).company == "Zeta"


def test_ac_text_naming_the_company_beats_the_ats_tenant() -> None:
    found = extract(
        "acme@myworkday.com",
        "",
        "Update",
        "Thank you for your interest in the Software Engineer Intern position at Fabrikam. "
        "After careful review, we have decided",
    )
    assert (found.company, found.role) == ("Fabrikam", "Software Engineer Intern")


def test_ac_company_stops_at_the_sentence_end() -> None:
    snippet = "Thank you for your interest in a position at Fabrikam. After careful review we ..."
    assert extract("a@x.example", "", "Update", snippet).company == "Fabrikam"
    assert (
        extract(
            "a@x.example",
            "",
            "Update",
            "Thanks for your interest in Adventure Works and for the time",
        ).company
        == "Adventure Works"
    )


@pytest.mark.parametrize(
    ("text", "role"),
    [
        ("We'd love to chat about the Robotics Intern role at Cyberdyne.", "Robotics Intern"),
        ("Interest in the Security Intern position at Wayne.", "Security Intern"),
        ("Job Title: Risk Analyst Intern\nLocation: Boston", "Risk Analyst Intern"),
        ("Job: Turbine Data Intern\nLocation: Denver", "Turbine Data Intern"),
        ("Position applied for: Cloud Support Intern", "Cloud Support Intern"),
        (
            "your application for the position of Data Engineer Intern. Thanks",
            "Data Engineer Intern",
        ),
        (
            "Thank you for your application for Embedded Software Intern. We regret",
            "Embedded Software Intern",
        ),
        ("you'd like to join our team as a Firmware Intern. We'll review", "Firmware Intern"),
        ("for the Game Developer Intern job. We have received", "Game Developer Intern"),
        (
            "received your application for the Cloud Engineer Intern opening and will review",
            "Cloud Engineer Intern",
        ),
    ],
)
def test_ac_role_patterns_in_the_snippet_or_body(text: str, role: str) -> None:
    assert extract("a@x.example", "", "Update", text).role == role
    assert extract("a@x.example", "", "Update", "Hi Sam,", text).role == role


def test_ac_a_role_does_not_start_with_the_company_name() -> None:
    assert (
        extract("a@hooli.example", "Hooli", "Offer - Hooli Backend Intern", "").role
        == "Backend Intern"
    )


def test_ac_a_role_pattern_does_not_swallow_the_sentence_before_it() -> None:
    snippet = "Thank you for your interest in Soylent and for the time you spent applying to the Product Design Intern position."
    assert extract("a@x.example", "", "Update", snippet).role == "Product Design Intern"


@pytest.mark.parametrize(
    "sign_off",
    [
        "Best regards,\nThe Orchid Pharma Talent Acquisition Team",
        "Sincerely,\nOrchid Pharma Recruiting",
        "Thanks,\nOrchid Pharma Careers",
        "Warm regards,\nThe Orchid Pharma Hiring Team",
        "Regards,\nOrchid Pharma Talent Acquisition",
        "Kind regards,\nOrchid Pharma University Recruiting Team",
    ],
)
def test_ac_company_from_the_sign_off(sign_off: str) -> None:
    found = extract(
        "a@mail.example", "Recruiting", "Update", "", f"Dear Sam,\n\nSorry.\n\n{sign_off}"
    )
    assert (found.company, found.company_source) == ("Orchid Pharma", "body")


def test_ac_a_sign_off_without_a_closing_word_needs_the_the_team_form() -> None:
    assert (
        extract("a@mail.example", "", "Hi", "", "Hello\nOrchid Pharma Recruiting").company is None
    )
    assert (
        extract("a@mail.example", "", "Hi", "", "Hello\nThe Orchid Pharma Recruiting Team").company
        == "Orchid Pharma"
    )


def test_ac_a_person_in_the_sign_off_is_not_a_company() -> None:
    body = "Hello\n\nBest regards,\nDana Whitfield\nTalent Partner"
    assert extract("a@mail.example", "", "Hi", "", body).company is None


@pytest.mark.parametrize(
    ("address", "name", "subject", "snippet", "company"),
    [
        (
            "no-reply@hackerrank.com",
            "HackerRank",
            "Invitation to take your assessment",
            "Hi Sam, Acme has invited you to take an online assessment.",
            "Acme",
        ),
        (
            "no-reply@codesignal.com",
            "CodeSignal",
            "Your CodeSignal assessment",
            "Initech invited you to complete the General Coding Assessment",
            "Initech",
        ),
        (
            "no-reply@codility.com",
            "Codility",
            "Codility test",
            "You have been invited by Lumen Optics to take a test",
            "Lumen Optics",
        ),
        (
            "no-reply@hirevue.com",
            "HireVue",
            "Complete your interview",
            "On behalf of Redwood Credit Union, we invite you",
            "Redwood Credit Union",
        ),
        (
            "calendar-notification@google.com",
            "Jordan Lee (via Google Calendar)",
            "Invitation: Acme Interview @ Tue Dec 2, 2026",
            "",
            "Acme",
        ),
        (
            "no-reply@zoom.us",
            "Zoom",
            "Meeting",
            "Topic: Globex Final Interview Time: Dec 3",
            "Globex",
        ),
        (
            "notifications@calendly.com",
            "Calendly",
            "Confirmed: 30 Minute Chat with Dana Whitfield - Globex",
            "",
            "Globex",
        ),
        (
            "no-reply@goodtime.io",
            "GoodTime",
            "Your interview with Tundra Mobility is scheduled",
            "",
            "Tundra Mobility",
        ),
    ],
)
def test_ac_vendor_senders_name_the_company_from_the_invitation_text(
    address: str, name: str, subject: str, snippet: str, company: str
) -> None:
    assert extract(address, name, subject, snippet).company == company


@pytest.mark.parametrize(
    ("address", "name"),
    [
        ("no-reply@hackerrank.com", "HackerRank"),
        ("no-reply@codesignal.com", "CodeSignal"),
        ("no-reply@codility.com", "Codility"),
        ("no-reply@hirevue.com", "HireVue"),
        ("no-reply@zoom.us", "Zoom"),
        ("calendar-notification@google.com", "Google Calendar"),
        ("notifications@calendly.com", "Calendly"),
        ("no-reply@goodtime.io", "GoodTime"),
        ("no-reply@modernloop.io", "ModernLoop"),
    ],
)
def test_ac_a_vendor_sender_never_becomes_the_company(address: str, name: str) -> None:
    assert extract(address, name, "Your interview is scheduled", "See you there").company is None


def test_ac_explicit_text_beats_the_ats_display_name_which_beats_the_domain() -> None:
    explicit = extract(GH, "Stark Dynamics", "Thanks for applying to Acme", "")
    assert (explicit.company, explicit.company_source) == ("Acme", "subject")
    display = extract("a@acme-corp.example", "Acme Robotics", "Update", "Hi")
    assert (display.company, display.company_source) == ("Acme Robotics", "display_name")
    domain = extract("a@acme-corp.example", "", "Update", "Hi")
    assert domain.company_source == "domain"


def test_ac_a_display_name_that_starts_the_domain_name_gets_its_fuller_form() -> None:
    assert (
        extract(
            "jobs@stark-dynamics.example", "Jobs at Stark", "Application confirmation", ""
        ).company
        == "Stark Dynamics"
    )
    assert (
        extract("jobs@acme-corp.example", "Jobs at Acme", "Application confirmation", "").company
        == "Acme"
    )


def test_ac_job_card_lines_give_company_and_role() -> None:
    body = "Application submitted\n\nOperations Intern\nWestbrook Hospitality - Chicago, IL\n\nGood luck!"
    found = extract(
        "indeedapply@indeed.com", "Indeed Apply", "Indeed Application: Operations Intern", "", body
    )
    assert (found.company, found.role) == ("Westbrook Hospitality", "Operations Intern")
    inline = extract(
        "indeedapply@indeed.com",
        "Indeed",
        "Application",
        "Support Engineer Intern - Soylent - Austin, TX.",
    )
    assert (inline.company, inline.role) == ("Soylent", "Support Engineer Intern")


def test_ac_the_body_is_bounded_and_extraction_stays_fast() -> None:
    hostile = ("Best regards,\n" * 2000) + ("applying to " * 5000) + ("x" * 100_000)
    start = time.perf_counter()
    extract(GH, "Acme", "Update", "snippet", hostile)
    extract("a@x.example", "", "Update", "", "a. " * 50_000)
    assert time.perf_counter() - start < 2.0


def test_ac_a_stray_lowercase_fragment_is_never_a_company() -> None:
    assert extract("a@x.example", "", "Update", "Thanks for applying to th").company is None
    assert extract("a@x.example", "", "Update", "Thanks for applying to HP.").company == "HP"
