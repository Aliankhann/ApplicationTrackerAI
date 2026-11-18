import json
import time
from pathlib import Path
from typing import Any

import pytest

from app.services.extraction import GENERIC_WORDS, VENDOR_NAMES, Extracted, extract

FIXTURE = Path(__file__).parent / "fixtures" / "extraction_cases.json"
CASES: list[dict[str, Any]] = json.loads(FIXTURE.read_text())
HOLDOUT: list[dict[str, Any]] = json.loads(
    (Path(__file__).parent / "fixtures" / "extraction_holdout.json").read_text()
)
BAD_COMPANIES = {n.lower() for n in VENDOR_NAMES | GENERIC_WORDS} | {"no reply", "team"}
VENDOR_DISPLAY_NAMES = [
    "Greenhouse",
    "Lever",
    "Workday",
    "Ashby",
    "iCIMS",
    "SmartRecruiters",
    "Workable",
    "Jobvite",
    "Taleo",
    "HackerRank",
    "CodeSignal",
    "Codility",
    "No Reply",
    "Notifications",
    "Team",
    "Careers",
    "Greenhouse Notifications",
    "Lever Hiring Team",
    "Workday Careers",
]


def _run(case: dict[str, Any]) -> Extracted:
    return extract(case["from_address"], case["from_name"], case["subject"], case["snippet"])


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_ac1_fixture_case_matches_exactly(case: dict[str, Any]) -> None:
    got = _run(case)
    assert (got.company, got.role) == (case["company"], case["role"])
    assert (got.company is None) == (got.company_source is None)
    assert (got.role is None) == (got.role_source is None)


def test_ac2_fixtures_never_yield_vendor_or_generic_company() -> None:
    for case in CASES:
        company = _run(case).company
        assert company is None or company.lower() not in BAD_COMPANIES


@pytest.mark.parametrize("name", VENDOR_DISPLAY_NAMES)
@pytest.mark.parametrize(
    "address", ["no-reply@greenhouse.io", "x@acme.example", "x@gmail.com", "x@workday.com"]
)
def test_ac2_vendor_display_name_never_becomes_company(name: str, address: str) -> None:
    company = extract(address, name, "Application received", "ok").company
    assert company is None or company.lower() not in BAD_COMPANIES


@pytest.mark.parametrize(
    "address",
    [
        "a@gmail.com",
        "a@mail.outlook.com",
        "a@hotmail.com",
        "a@yahoo.com",
        "a@icloud.com",
        "a@proton.me",
        "a@protonmail.com",
        "a@live.com",
        "a@aol.com",
        "a@gmx.net",
        "a@gmx.de",
        "a@mail.com",
        "a@cs.stateuniv.edu",
        "a@ox.ac.uk",
        "a@univ.edu.au",
    ],
)
def test_ac3_generic_and_academic_domains_yield_no_domain_company(address: str) -> None:
    got = extract(address, "Jane Smith", "Hello", "Hi")
    assert got.company is None
    assert got.company_source != "domain"


@pytest.mark.parametrize(
    "subject",
    [
        "Application for the Summer Program position",
        "Quick chat | Welcome",
        "Your application: Hello",
    ],
)
def test_ac4_role_without_job_noun_is_none(subject: str) -> None:
    assert extract("a@acme.example", "", subject, "").role is None


@pytest.mark.parametrize(
    "subject",
    [
        "Application for Software Engineer Intern (R12345)",
        "Application for Software Engineer Intern #4567",
        "Application for Software Engineer Intern - Req 123",
        "Application for Software Engineer Intern JR-2025-001",
    ],
)
def test_ac4_requisition_ids_are_stripped(subject: str) -> None:
    assert extract("a@acme.example", "", subject, "").role == "Software Engineer Intern"


@pytest.mark.parametrize(
    ("address", "name", "subject", "snippet"),
    [
        ("", "", "", ""),
        ("@", "<>", "|", "-"),
        ("a@", " ", ":", "at"),
        ("a@.", "via", "at | - ", "for the position"),
        ("<a@b@c>", "@", "Application for", "position of"),
        ("a@x..y", "\u0000", "Thank you for applying to", "application for the"),
        ("a@wd5.myworkdayjobs.com", "", "(", ")"),
        ("a@a.b.c.d.e.f", "X" * 5000, "Y " * 5000, "é" * 5000),
        ("\uff41@\uff47mail.com", "\ufb01 \u0153", "\u0153uvre | \ufb01nal", "\u01c4"),
    ],
)
def test_ac5_malformed_input_never_raises(
    address: str, name: str, subject: str, snippet: str
) -> None:
    assert isinstance(extract(address, name, subject, snippet), Extracted)


def test_ac5_none_values_never_raise() -> None:
    assert extract(None, None, None, None) == Extracted(None, None, None, None)  # type: ignore[arg-type]


def test_sources_are_stable_identifiers() -> None:
    assert extract("a@greenhouse.io", "Acme Hiring Team", "x", "").company_source == "display_name"
    assert (
        extract("a@gmail.com", "", "Thank you for applying to Acme", "").company_source == "subject"
    )
    assert extract("a@careers.acme.example", "", "x", "").company_source == "domain"
    assert extract("a@gmail.com", "", "x", "application for Data Analyst.").role_source == "snippet"


def _precision_recall(cases: list[dict[str, Any]], field: str) -> tuple[float, float]:
    produced = [(getattr(_run(c), field), c[field]) for c in cases if getattr(_run(c), field)]
    expected = sum(1 for c in cases if c[field])
    correct = sum(1 for got, want in produced if got == want)
    return correct / len(produced), correct / expected


@pytest.mark.parametrize("field", ["company", "role"])
def test_ac6_precision_on_fixture_set(field: str) -> None:
    precision, recall = _precision_recall(CASES, field)
    print(f"{field}: precision={precision:.3f} recall={recall:.3f}")
    assert precision >= 0.95


@pytest.mark.parametrize("field", ["company", "role"])
def test_ac6_precision_on_holdout_set(field: str) -> None:
    assert len(HOLDOUT) >= 25
    precision, recall = _precision_recall(HOLDOUT, field)
    print(f"holdout {field}: precision={precision:.3f} recall={recall:.3f}")
    assert precision >= 0.95


@pytest.mark.parametrize(
    "unit", ["engineer (", "Intern at ", "application for ", "Acme | ", "a" * 50 + " - ", " at "]
)
def test_adversarial_input_is_linear_time(unit: str) -> None:
    text = unit * (100_000 // len(unit))
    start = time.perf_counter()
    extract("a@greenhouse.io", text, text, text)
    extract("a@gmail.com", text, text, text)
    assert time.perf_counter() - start <= 1.0


def test_person_display_name_needs_corroboration() -> None:
    assert extract("a@greenhouse.io", "Priya Natarajan", "Hello", "").company is None
    assert extract("a@greenhouse.io", "Priya Natarajan", "Applying to Wavecrest", "").company == (
        "Wavecrest"
    )


def test_explicit_subject_company_beats_display_and_domain() -> None:
    got = extract("a@velmora.example", "Velmora Careers", "Thank you for applying to Orrin Bio", "")
    assert (got.company, got.company_source) == ("Orrin Bio", "subject")


def test_conflicting_explicit_companies_give_none() -> None:
    got = extract("a@gmail.com", "", "Thank you for applying to Orrin Bio", "applying to Zeta Co")
    assert got.company is None


def test_vendor_lookalikes_never_become_company() -> None:
    for address in ("a@workdayhr-notify.example", "a@greenhouse-software.example"):
        assert extract(address, "Lever Staffing", "Update", "").company is None
