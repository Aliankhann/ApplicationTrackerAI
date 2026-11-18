from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.services.templates import (
    VARIABLES,
    TemplateError,
    Tone,
    format_applied_date,
    render,
    subject_for,
    validate_template,
)

FULL = {
    "recruiter_first_name": "Dana",
    "role": "Data Intern",
    "company": "Acme",
    "applied_date": "March 3",
    "your_name": "Sam",
}
ALL_VARS = "{recruiter_first_name}|{role}|{company}|{applied_date}|{your_name}"
RAW = ("{", "}")


def test_ac5_every_variable_is_substituted() -> None:
    out = render(ALL_VARS, FULL)
    assert "Dana|Data Intern|Acme|March 3|Sam" in out


@pytest.mark.parametrize(
    ("tone", "greeting", "sign_off"),
    [
        ("short", "Hi Dana,\n\n", "Thanks,\nSam"),
        ("warm", "Hi Dana, I hope you're doing well.\n\n", "Best,\nSam"),
        ("formal", "Dear Dana,\n\n", "Kind regards,\nSam"),
    ],
)
def test_ac5_every_tone_preset_wraps_the_body(tone: Tone, greeting: str, sign_off: str) -> None:
    assert render("Body {role}.", FULL, tone) == f"{greeting}Body Data Intern.\n\n{sign_off}"


@pytest.mark.parametrize(
    ("key", "fallback"),
    [
        ("recruiter_first_name", "Hi there,"),
        ("role", "the role"),
        ("company", "your team"),
        ("applied_date", "recently"),
    ],
)
def test_ac5_missing_values_use_fallbacks(key: str, fallback: str) -> None:
    for missing in (None, "", "  \n "):
        out = render(f"{{{key}}}", {**FULL, key: missing})
        assert fallback in out


def test_ac5_missing_name_removes_sign_off_cleanly() -> None:
    assert render("Body.", {**FULL, "your_name": None}) == "Hi Dana,\n\nBody."
    assert render("Body.", {}) == "Hi there,\n\nBody."


def test_ac5_substitution_is_single_pass_and_capped() -> None:
    out = render("{role} / {company}", {"role": "{company}", "company": "Acme"})
    assert "company / Acme" in out and "{" not in out
    long = render("{role}", {"role": "x" * 500})
    assert "x" * 80 in long and "x" * 81 not in long


def test_ac5_values_are_plain_text() -> None:
    out = render("{role}", {"role": "a\nb\x00c\x07d\r\ne"})
    assert "a b" in out and "\x00" not in out and "\x07" not in out
    assert "a bcd e" in out


@pytest.mark.parametrize(
    "bad", ["{nope}", "{role", "role}", "{{role}}", "{role.x}", "{0}", "<b>x</b>", "a <br> b"]
)
def test_ac5_render_rejects_unsafe_templates(bad: str) -> None:
    with pytest.raises(TemplateError):
        render(bad, FULL)
    with pytest.raises(TemplateError):
        validate_template(bad)


_value = st.one_of(
    st.none(),
    st.text(max_size=200),
    st.sampled_from(
        ["{role}", "}{", "{{x}}", "a\nb", "\x00{company}\x1f", *(f"{{{v}}}" for v in VARIABLES)]
    ),
)


@given(
    context=st.fixed_dictionaries({v: _value for v in VARIABLES}),
    tone=st.sampled_from(["short", "warm", "formal"]),
    picks=st.lists(st.sampled_from(VARIABLES), max_size=8),
)
def test_ac5_property_never_outputs_raw_placeholder(
    context: dict[str, str | None], tone: Tone, picks: list[str]
) -> None:
    template = " ".join(f"{{{p}}}" for p in picks) or "plain"
    out = render(template, context, tone)
    assert not any(ch in out for ch in RAW)
    assert not any(ord(ch) < 32 and ch != "\n" for ch in out)


def test_ac6_applied_date_respects_timezone() -> None:
    instant = datetime(2026, 3, 3, 23, 30, tzinfo=UTC)
    assert format_applied_date(instant) == "March 3"
    assert format_applied_date(instant, ZoneInfo("Asia/Tokyo")) == "March 4"
    assert format_applied_date(instant, ZoneInfo("America/Los_Angeles")) == "March 3"


def test_ac7_subject_adds_re_once_and_strips_crlf() -> None:
    assert subject_for("Your application") == "Re: Your application"
    assert subject_for("Re: Your application") == "Re: Your application"
    assert subject_for("RE: hi") == "RE: hi"
    assert subject_for("a\r\nBcc: x@y.test") == "Re: a Bcc: x@y.test"
    assert len(subject_for("s" * 2000)) == 998


@pytest.mark.parametrize("ch", ["‮", "​", "⁦", "⁩", "﻿", "؜", "\x00"])
def test_ac5_bidi_zero_width_and_nul_stripped_from_values(ch: str) -> None:
    out = render("Hi {company}", {"company": f"A{ch}B"})
    assert ch not in out and "AB" in out


@pytest.mark.parametrize("ch", ["‮", "​", "\x00", "\x07", "\r"])
def test_ac3_template_with_control_or_invisible_chars_rejected(ch: str) -> None:
    with pytest.raises(TemplateError):
        validate_template(f"hi{ch} {{role}}")
    validate_template("line one\n\tline two {role}")


def test_ac3_comparison_signs_are_not_html() -> None:
    validate_template("a < b and c > d, 5 <3")
    for tag in ("<b>", "</b>", "<!-- x -->", "<script"):
        with pytest.raises(TemplateError):
            validate_template(tag)


def test_ac5_unknown_tone_raises_template_error() -> None:
    with pytest.raises(TemplateError, match="tone"):
        render("x", FULL, "bogus")  # type: ignore[arg-type]


def test_ac6_naive_datetime_rejected_and_none_tz_is_utc() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        format_applied_date(datetime(2026, 3, 3, 0, 30))
    assert format_applied_date(datetime(2026, 3, 3, 23, 30, tzinfo=UTC), None) == "March 3"
    ny = ZoneInfo("America/New_York")
    assert format_applied_date(datetime(2026, 3, 8, 6, 30, tzinfo=UTC), ny) == "March 8"


def test_ac7_subject_strips_invisible_and_handles_empty() -> None:
    assert subject_for("a\x00b‮c​d") == "Re: abcd"
    assert subject_for("") == "Re: Following up"
    assert subject_for("‮\x00 \r\n") == "Re: Following up"
    assert subject_for("a\t\t b") == "Re: a b"


def test_ac7_subject_capped_by_utf8_bytes_at_character_boundary() -> None:
    out = subject_for("é" * 2000)
    encoded = out.encode("utf-8")
    assert len(encoded) <= 998 and out.startswith("Re: é") and set(out[4:]) == {"é"}
