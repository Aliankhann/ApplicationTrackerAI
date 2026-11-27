"""Phase 1: cleaning a message body before it is classified or mined (pure, in memory)."""

from app.services.body_text import body_window, clean_body, prepare_body

REPLY = """Great, I'll send a calendar invite shortly.

Priya

On Tue, Nov 11, 2026 at 9:00 AM Sam Student <sam.student@mail.example> wrote:
> Hi Priya, Thursday works.
> Unfortunately we cannot move forward with your application.
"""


def test_ac_quoted_replies_are_removed() -> None:
    cleaned = clean_body(REPLY)
    assert cleaned == "Great, I'll send a calendar invite shortly.\n\nPriya"
    assert "Unfortunately" not in cleaned


def test_ac_original_message_and_outlook_headers_cut_the_rest() -> None:
    outlook = "Thanks, see you then.\n\nFrom: Sam <s@x.example>\nSent: Monday\nTo: Priya\nOld text"
    assert clean_body(outlook) == "Thanks, see you then."
    forwarded = "Hello\n-----Original Message-----\nold text"
    assert clean_body(forwarded) == "Hello"


def test_ac_lines_starting_with_a_quote_marker_are_dropped() -> None:
    assert clean_body("Fresh line\n> quoted\n>> more quoted\nAnother fresh") == (
        "Fresh line\n\nAnother fresh"
    )


def test_ac_footers_and_unsubscribe_blocks_are_removed_but_content_stays() -> None:
    body = (
        "Application submitted. Software Engineer Intern. We will let you know. "
        "Manage your Indeed job alerts\n\n"
        "You are receiving this email because you applied.\n"
        "Unsubscribe | Privacy Policy | View in browser\n"
        "This is an automated message. Please do not reply to this email."
    )
    cleaned = clean_body(body)
    assert "Application submitted" in cleaned and "We will let you know" in cleaned
    for junk in ("job alerts", "receiving", "Unsubscribe", "automated", "do not reply"):
        assert junk not in cleaned


def test_ac_the_sign_off_is_kept_for_company_extraction() -> None:
    body = (
        "Thank you for applying.\n\nBest regards,\nThe Acme Talent Acquisition Team\n\nUnsubscribe"
    )
    assert clean_body(body).endswith("Best regards,\nThe Acme Talent Acquisition Team")


def test_ac_signature_noise_is_removed() -> None:
    body = (
        "See you Tuesday.\n\nElena Park\nTalent Partner\nelena@marlow.example | 555-0142\n"
        "https://example.com/careers\n[image: logo]\nSent from my iPhone\n"
        "This email is confidential and intended for the recipient only.\n-- \nOld signature"
    )
    cleaned = clean_body(body)
    assert cleaned == "See you Tuesday.\n\nElena Park\nTalent Partner"


def test_ac_known_ats_links_survive_for_tenant_extraction() -> None:
    body = "Apply link:\nhttps://acme.wd5.myworkdayjobs.com/en-US/Careers/job/1\nBye"
    assert "acme.wd5.myworkdayjobs.com" in clean_body(body)


def test_ac_window_keeps_the_start_and_the_end_and_is_bounded() -> None:
    long = "start " + "x " * 5000 + "Best regards,\nThe Acme Recruiting Team"
    window = prepare_body(long)
    assert window.startswith("start") and window.endswith("The Acme Recruiting Team")
    assert len(window) <= 2500
    assert body_window("short") == "short"


def test_ac_empty_and_missing_text_are_safe() -> None:
    assert clean_body("") == ""
    assert prepare_body("") == ""
