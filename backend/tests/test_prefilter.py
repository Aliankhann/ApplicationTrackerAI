import json
import time
from pathlib import Path
from typing import Any

import pytest

from app.services.prefilter import ATS_DOMAINS, EmailMeta, prefilter, sender_domain

FIXTURE = Path(__file__).parent / "fixtures" / "prefilter_cases.json"
CASES: list[dict[str, Any]] = json.loads(FIXTURE.read_text())


def _meta(case: dict[str, Any]) -> EmailMeta:
    return EmailMeta(case["from_address"], case["from_name"], case["subject"], case["snippet"])


def _email(address: str, subject: str = "", snippet: str = "") -> EmailMeta:
    return EmailMeta(address, "", subject, snippet)


@pytest.mark.parametrize("domain", ATS_DOMAINS)
def test_ac1_ats_domain_and_subdomain_kept(domain: str) -> None:
    for address in (f"a@{domain}", f"a@mail.{domain}", f"Name <a@x.y.{domain.upper()}>"):
        assert prefilter(_email(address)).reason == "ats_domain"


@pytest.mark.parametrize(
    "address", ["a@notgreenhouse.io", "a@greenhouse.io.evil.com", "a@fakelever.co", "greenhouse.io"]
)
def test_ac1_lookalike_domains_not_ats(address: str) -> None:
    assert not prefilter(_email(address)).keep


@pytest.mark.parametrize(
    "subject,snippet",
    [
        ("We received your application", ""),
        ("Interview invitation", ""),
        ("", "Complete the online assessment"),
        ("Update", "Unfortunately, we will not be moving forward with your application"),
        ("Your offer letter", ""),
        ("Hello", "I am a recruiter at Acme"),
    ],
)
def test_ac2_company_job_mail_kept_by_keyword(subject: str, snippet: str) -> None:
    decision = prefilter(_email("hr@company.example", subject, snippet))
    assert decision.keep
    assert decision.reason == "job_keyword"


@pytest.mark.parametrize(
    "case",
    [
        c
        for c in CASES
        if c["id"].split("_")[0]
        in {"newsletter", "receipt", "shipping", "social", "bank", "promo", "deals", "marketing"}
    ],
    ids=lambda c: c["id"],
)
def test_ac3_non_job_mail_dropped(case: dict[str, Any]) -> None:
    decision = prefilter(_meta(case))
    assert not decision.keep
    assert decision.reason == "no_signal"


@pytest.mark.parametrize(
    "address", ["", "   ", "@@@", "foo@", "<>", "not an email", "a@b@c@", "\x00@\n"]
)
def test_ac4_malformed_inputs_never_raise(address: str) -> None:
    assert isinstance(prefilter(_email(address)).keep, bool)
    assert isinstance(sender_domain(address), str)


def test_ac4_empty_everything() -> None:
    assert prefilter(EmailMeta("", "", "", "")).reason == "no_signal"


def test_sender_domain_forms() -> None:
    assert sender_domain('"Acme <x@acme.com>" <No-Reply@ACME.com>') == "acme.com"
    assert sender_domain("Acme <no-reply@acme.com>") == "acme.com"
    assert sender_domain("garbage") == ""


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_ac5_fixture_matches_expected(case: dict[str, Any]) -> None:
    assert prefilter(_meta(case)).keep is case["expected_keep"]


def test_ac5_fixture_size_and_full_recall() -> None:
    assert len(CASES) >= 40
    job_cases = [c for c in CASES if c["expected_keep"]]
    kept = [c for c in job_cases if prefilter(_meta(c)).keep]
    assert len(kept) == len(job_cases)


def _longest_common_substring_over(a: str, b: str, limit: int) -> bool:
    a, b = a.lower(), b.lower()
    return any(a[i : i + limit + 1] in b for i in range(len(a) - limit))


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_ac6_reason_leaks_no_email_text(case: dict[str, Any]) -> None:
    reason = prefilter(_meta(case)).reason
    for field in (case["subject"], case["snippet"]):
        assert not _longest_common_substring_over(reason, field, 3)


def test_perf_large_input_is_fast() -> None:
    text = ("lorem ipsum dolor sit amet " * 4000)[:100_000]
    start = time.perf_counter()
    decision = prefilter(EmailMeta("a@b.example", "n", "", text))
    assert (
        time.perf_counter() - start < 1.0
    )  # generous for slow CI; catastrophic backtracking takes far longer
    assert not decision.keep
