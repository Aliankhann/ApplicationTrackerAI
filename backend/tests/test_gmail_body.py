"""Phase 1: message text read in memory (plain text preferred, HTML stripped, never attachments)."""

import base64
from typing import Any

import httpx
import pytest

from app.providers.gmail import GmailNotFound
from app.providers.gmail.body import html_to_text, message_text
from app.providers.gmail.fake import FakeGmailClient
from tests.fake_gmail_api import FakeGmailApi
from tests.fixtures.gmail_threads import OWNER
from tests.test_rest_gmail import NOW, make


def b64(text: str, charset: str = "utf-8") -> str:
    return base64.urlsafe_b64encode(text.encode(charset)).decode().rstrip("=")


def part(
    mime: str, text: str, charset: str = "utf-8", label: str | None = None, **extra: Any
) -> dict[str, Any]:
    headers = [{"name": "Content-Type", "value": f'{mime}; charset="{label or charset}"'}]
    return {"mimeType": mime, "headers": headers, "body": {"data": b64(text, charset)}, **extra}


def multipart(*parts: dict[str, Any]) -> dict[str, Any]:
    return {"mimeType": "multipart/alternative", "parts": list(parts)}


def test_ac_prefers_text_plain_over_html() -> None:
    payload = multipart(
        part("text/plain", "Plain: your application was received."),
        part("text/html", "<p>Html: <b>different</b></p>"),
    )
    assert message_text(payload, 8000) == "Plain: your application was received."


def test_ac_falls_back_to_html_stripped_to_text() -> None:
    html = "<html><head><style>p{color:red}</style></head><body><script>evil()</script>"
    html += "<p>Hello   Sam,</p><p>We  received\nyour application.</p><br>Regards</body></html>"
    text = message_text(multipart(part("text/html", html)), 8000)
    assert text == "Hello Sam,\n\nWe received your application.\n\nRegards"
    assert "evil" not in text and "color" not in text


def test_ac_html_to_text_survives_broken_markup() -> None:
    assert "kept" in html_to_text("<div><p>kept <b>text</div></p></i><<>")


def test_ac_a_stub_plain_part_yields_to_the_real_html_part() -> None:
    payload = multipart(
        part("text/plain", "View this email in your browser"),
        part(
            "text/html", "<p>Thank you for applying to the Data Intern role at Acme. Good luck!</p>"
        ),
    )
    assert "Data Intern role at Acme" in message_text(payload, 8000)


def test_ac_decodes_base64url_and_other_charsets_safely() -> None:
    latin = part("text/plain", "Café Lumière: candidature reçue", "iso-8859-1")
    assert message_text(latin, 8000) == "Café Lumière: candidature reçue"
    unknown = part(
        "text/plain", "Hello there, this is long enough to count as text", label="x-nonsense"
    )
    assert message_text(unknown, 8000).startswith("Hello there")
    broken = {"mimeType": "text/plain", "body": {"data": "!!!not base64!!!"}}
    assert message_text(broken, 8000) == ""


def test_ac_truncates_to_max_chars() -> None:
    assert len(message_text(part("text/plain", "word " * 5000), 100)) == 100


def test_ac_skips_attachments_and_non_text_parts() -> None:
    attachment = part("text/plain", "SECRET ATTACHED TEXT", filename="cv.txt")
    remote = {"mimeType": "text/plain", "body": {"attachmentId": "abc", "size": 90000}}
    image = {"mimeType": "image/png", "body": {"data": b64("png")}}
    payload = multipart(attachment, remote, image, part("text/plain", "Visible message body."))
    assert message_text(payload, 8000) == "Visible message body."


def test_ac_garbage_payloads_give_empty_text() -> None:
    payloads: list[Any] = [None, "x", [], {"parts": "no"}, {"mimeType": "text/plain"}]
    for payload in payloads:
        assert message_text(payload, 100) == ""


def test_ac_rest_client_fetches_full_format_for_one_message_and_never_an_attachment() -> None:
    api = FakeGmailApi(OWNER)
    api.payloads["m-1"] = part("text/plain", "Hello Sam, interview invitation.")
    text = make(api).get_message_text("m-1", max_chars=500)
    assert text == "Hello Sam, interview invitation."
    paths = [u.path for u in api.gmail_urls()]
    assert paths[-1].endswith("/messages/m-1")
    assert not any("attachments" in p for p in paths)
    assert api.gmail_urls()[-1].params["format"] == "full"


def test_ac_rest_client_missing_message_is_not_found() -> None:
    with pytest.raises(GmailNotFound):
        make(FakeGmailApi(OWNER)).get_message_text("gone")


def test_ac_rest_client_failures_never_carry_message_text() -> None:
    api = FakeGmailApi(OWNER)
    api.payloads["m-1"] = part("text/plain", "TOP SECRET BODY")
    api.fail("/messages", 500)
    client = make(api)
    with pytest.raises(Exception) as caught:
        client.get_message_text("m-1")
    assert "TOP SECRET" not in repr(caught.value) and "TOP SECRET" not in str(caught.value)


def test_ac_fake_client_serves_fixture_bodies_and_truncates() -> None:
    fake = FakeGmailClient(OWNER, now=NOW)
    fake.set_body("m1", "x" * 50)
    assert fake.get_message_text("m1", 10) == "x" * 10
    assert fake.get_message_text("unknown") == ""
    assert fake.body_fetches == ["m1", "unknown"]


def test_ac_html_to_text_is_not_slow_on_hostile_input() -> None:
    import time

    start = time.perf_counter()
    html_to_text("<div>" * 20000 + "x" * 100000)
    assert time.perf_counter() - start < 2


@pytest.mark.parametrize(
    "transport", [httpx.MockTransport(lambda r: httpx.Response(200, text="not json"))]
)
def test_ac_malformed_response_is_a_gmail_error(transport: httpx.MockTransport) -> None:
    from app.providers.gmail import GmailError
    from app.providers.gmail.rest import RestGmailClient

    client = RestGmailClient(lambda _refresh: "tok", httpx.Client(transport=transport))
    with pytest.raises(GmailError):
        client.get_message_text("m-1")


def test_ac_total_decoded_bytes_across_parts_are_capped() -> None:
    from app.providers.gmail.body import MAX_TOTAL_BYTES

    big = "word " * 40_000  # 200 KB each
    payload = multipart(
        *(part("text/plain", big) for _ in range(5)), part("text/plain", "TAIL-MARKER")
    )
    text = message_text(payload, 10_000_000)
    assert "TAIL-MARKER" not in text and len(text.encode()) <= MAX_TOTAL_BYTES + 100


def test_ac_the_full_request_carries_a_fields_mask() -> None:
    api = FakeGmailApi(OWNER)
    api.payloads["m-1"] = part("text/plain", "Hello Sam, interview invitation.")
    make(api).get_message_text("m-1")
    fields = api.gmail_urls()[-1].params["fields"]
    assert fields == "payload(mimeType,filename,headers,body/data,parts)"
