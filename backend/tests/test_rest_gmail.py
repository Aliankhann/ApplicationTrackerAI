"""US-31/US-65 real Google implementations, against an httpx MockTransport fake of Google."""

import base64
import uuid
from datetime import UTC, datetime, timedelta
from email import message_from_bytes
from email.header import decode_header, make_header
from email.policy import default
from typing import Any

import httpx
import pytest

from app.providers.gmail import (
    DraftRequest,
    GmailAuthRevoked,
    GmailError,
    GmailHistoryExpired,
    GmailNotFound,
    GmailRateLimited,
)
from app.providers.gmail.draft_message import build_raw_message, cap_references
from app.providers.gmail.rest import RestGmailClient
from app.providers.google.oidc import OidcConfig
from app.providers.google.revoke import GoogleTokenRevoker, RevokeResult
from app.providers.google.tokens import (
    AccessTokenCache,
    CachedAccessTokens,
    refresh_access_token,
)
from tests.fake_gmail_api import REFRESH_TOKEN, REVOKE_URL, FakeGmailApi, api_message
from tests.fake_google import CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, TOKEN_URL
from tests.fixtures.gmail_threads import OWNER, build_threads

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
CONFIG = OidcConfig(CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, "iss", "auth", TOKEN_URL, "jwks")


def make(api: FakeGmailApi, cache: AccessTokenCache | None = None) -> RestGmailClient:
    http = httpx.Client(transport=api.transport())
    tokens = CachedAccessTokens(
        uuid.uuid4(), REFRESH_TOKEN, CONFIG, http, cache or AccessTokenCache(), lambda: NOW
    )
    return RestGmailClient(tokens, http)


@pytest.fixture
def api() -> FakeGmailApi:
    return FakeGmailApi.from_metas(OWNER, build_threads(NOW))


def test_us31_requests_are_metadata_only_and_never_full_or_raw(api: FakeGmailApi) -> None:
    api.history = [{"messagesAdded": [{"message": {"id": "m1", "threadId": "t-confirm"}}]}]
    client = make(api)
    client.get_profile()
    client.list_threads("newer_than:90d")
    client.get_thread("t-interview")
    client.get_threads(["t-confirm", "t-reject"])
    client.get_reply_recipient("t-interview")
    client.list_history("100")
    client.create_draft(
        DraftRequest("t-interview", "<a@x>", "<a@x>", "Re: Hi", "Body", "to@x.test")
    )
    client.get_draft("d-1")
    for url in api.gmail_urls():
        assert url.params.get("format") in (None, "metadata", "minimal"), url.path
        assert "raw" not in url.params.get_list("format") and "full" not in str(url)
    fetched = [u for u in api.gmail_urls() if u.path.endswith("/threads/t-interview")]
    assert fetched[0].params.get_list("metadataHeaders") == [
        "From",
        "Subject",
        "Message-ID",
        "References",
        "In-Reply-To",
    ]
    assert fetched[0].params["format"] == "metadata"


def test_us31_list_threads_paginates_with_query_and_page_size(api: FakeGmailApi) -> None:
    client = make(api)
    seen: list[str] = []
    token: str | None = None
    while True:
        page, token = client.list_threads("newer_than:90d", token)
        seen += [t.thread_id for t in page]
        if token is None:
            break
    assert sorted(seen) == sorted(build_threads(NOW))
    first = next(u for u in api.gmail_urls() if u.path.endswith("/threads"))
    assert first.params["q"] == "newer_than:90d" and first.params["maxResults"] == "100"


def test_us31_list_threads_with_no_match_is_empty() -> None:
    assert make(FakeGmailApi(OWNER)).list_threads("newer_than:1d") == ([], None)


def test_us31_history_lists_message_added_changes_and_pages(api: FakeGmailApi) -> None:

    def added(thread_id: str) -> dict[str, Any]:
        return {"messagesAdded": [{"message": {"id": "m", "threadId": thread_id}}]}

    api.history = [added("t-a"), added("t-a"), added("t-b")]
    client = make(api)
    page = client.list_history("100")
    assert page.changed_thread_ids == ("t-a",) and page.next_page_token == "1"  # noqa: S105
    assert page.history_id == "5000"
    last = client.list_history("100", "2")
    assert last.changed_thread_ids == ("t-b",) and last.next_page_token is None
    url = next(u for u in api.gmail_urls() if u.path.endswith("/history"))
    assert url.params["startHistoryId"] == "100" and url.params["historyTypes"] == "messageAdded"


def test_us31_history_404_means_expired_but_thread_404_means_not_found(api: FakeGmailApi) -> None:
    api.fail("/history", 404)
    client = make(api)
    with pytest.raises(GmailHistoryExpired):
        client.list_history("1")
    with pytest.raises(GmailNotFound):
        client.get_thread("t-missing")
    assert client.get_draft("d-nope") is None


def test_us31_401_refreshes_once_then_retries(api: FakeGmailApi) -> None:
    client = make(api)
    client.get_profile()
    api.expire_access_token()
    assert client.get_profile().email == OWNER
    assert api.refresh_count == 2  # first use, then once after the 401


def test_us31_persistent_401_raises_auth_revoked(api: FakeGmailApi) -> None:
    client = make(api)
    api.reject_all = True
    refreshes_before = api.refresh_count
    with pytest.raises(GmailAuthRevoked):
        client.get_profile()
    assert api.refresh_count - refreshes_before == 2  # initial token plus one forced refresh


def test_us31_invalid_grant_on_refresh_raises_auth_revoked(api: FakeGmailApi) -> None:
    api.refresh_error = "invalid_grant"
    with pytest.raises(GmailAuthRevoked):
        make(api).get_profile()


@pytest.mark.parametrize(
    ("status", "body", "headers"),
    [
        (403, {"error": {"errors": [{"reason": "rateLimitExceeded"}]}}, {"Retry-After": "7"}),
        (403, {"error": {"errors": [{"reason": "userRateLimitExceeded"}]}}, {"Retry-After": "7"}),
        (403, {"error": {"status": "RESOURCE_EXHAUSTED"}}, {"Retry-After": "7"}),
        (429, {}, {"Retry-After": "7"}),
        (503, {}, {"Retry-After": "7"}),
    ],
)
def test_us31_rate_limits_and_server_errors_carry_retry_after(
    api: FakeGmailApi, status: int, body: dict[str, object], headers: dict[str, str]
) -> None:
    api.fail("/profile", status, body, **headers)
    with pytest.raises(GmailRateLimited) as raised:
        make(api).get_profile()
    assert raised.value.retry_after == 7.0


def test_us31_rate_limit_without_header_has_no_retry_after(api: FakeGmailApi) -> None:
    api.fail("/profile", 429)
    with pytest.raises(GmailRateLimited) as raised:
        make(api).get_profile()
    assert raised.value.retry_after is None


def test_us31_other_403_is_a_plain_error_not_a_rate_limit(api: FakeGmailApi) -> None:
    api.fail("/profile", 403, {"error": {"errors": [{"reason": "insufficientPermissions"}]}})
    with pytest.raises(GmailError) as raised:
        make(api).get_profile()
    assert not isinstance(raised.value, GmailRateLimited | GmailAuthRevoked)


def test_us31_transport_failure_is_a_gmail_error_without_details() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret-host-detail")

    http = httpx.Client(transport=httpx.MockTransport(boom))
    client = RestGmailClient(lambda _: "t", http)
    with pytest.raises(GmailError) as raised:
        client.get_profile()
    assert "secret" not in str(raised.value)


def test_us31_thread_parsing_matches_fixture_round_trip(api: FakeGmailApi) -> None:
    client = make(api)
    expected = build_threads(NOW)
    for thread_id, messages in expected.items():
        thread = client.get_thread(thread_id)
        assert list(thread.messages) == messages  # from_user, dates, ids, labels, snippet
    sent = client.get_thread("t-sent")
    assert sent.last_sender_is_user and sent.last_message_at.tzinfo is UTC


def test_us31_from_user_ignores_case_and_profile_is_fetched_once(api: FakeGmailApi) -> None:
    api.threads["t-x"] = [
        {**api_message(build_threads(NOW)["t-sent"][0]), "id": "x1", "threadId": "t-x"}
    ]
    api.threads["t-x"][0]["payload"]["headers"][0]["value"] = f"Me <{OWNER.upper()}>"
    client = make(api)
    assert client.get_thread("t-x").messages[0].from_user is True
    client.get_thread("t-confirm")
    profiles = [u for u in api.gmail_urls() if u.path.endswith("/profile")]
    assert len(profiles) == 1


def test_us31_internal_date_parsed_as_utc_and_messages_sorted(api: FakeGmailApi) -> None:
    early, late = ({"internalDate": str(ms)} for ms in (1_767_268_800_000, 1_767_355_200_000))
    base = api_message(build_threads(NOW)["t-confirm"][0])
    api.threads["t-order"] = [{**base, **late, "id": "b"}, {**base, **early, "id": "a"}]
    thread = make(api).get_thread("t-order")
    assert [m.message_id for m in thread.messages] == ["a", "b"]
    assert thread.messages[0].sent_at == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert thread.messages[0].sent_at.utcoffset() == timedelta(0)


def test_us31_encoded_name_and_escaped_snippet_are_decoded(api: FakeGmailApi) -> None:
    message = api_message(build_threads(NOW)["t-confirm"][0])
    message["payload"]["headers"][0]["value"] = "=?utf-8?q?Zo=C3=AB_Recruiter?= <jobs@acme.example>"
    message["snippet"] = "It&#39;s a &quot;match&quot; &amp; more"
    api.threads["t-enc"] = [message]
    meta = make(api).get_thread("t-enc").messages[0]
    assert (meta.from_name, meta.from_address) == ("Zoë Recruiter", "jobs@acme.example")
    assert meta.snippet == 'It\'s a "match" & more'


def test_us31_get_threads_is_bounded_to_five_concurrent_and_ordered(api: FakeGmailApi) -> None:
    for i in range(20):
        api.threads[f"t{i:02}"] = [api_message(build_threads(NOW)["t-confirm"][0])]
    api.delay = 0.02
    ids = [f"t{i:02}" for i in range(20)]
    result = make(api).get_threads(ids)
    assert [t.thread_id for t in result] == ids
    assert 1 < api.max_in_flight <= 5


def test_us31_get_threads_leaves_out_a_missing_thread(api: FakeGmailApi) -> None:
    found = make(api).get_threads(["t-confirm", "t-gone"])
    assert [t.thread_id for t in found] == ["t-confirm"]


def test_us31_reply_recipient_prefers_reply_to_and_skips_own_messages(api: FakeGmailApi) -> None:
    base = api_message(build_threads(NOW)["t-confirm"][0])
    theirs = {**base, "id": "a", "internalDate": "1000"}
    theirs["payload"] = {
        "headers": [
            {"name": "From", "value": "Jobs <jobs@acme.example>"},
            {"name": "Reply-To", "value": "recruiting@acme.example"},
        ]
    }
    mine = {**base, "id": "b", "internalDate": "2000"}
    mine["payload"] = {"headers": [{"name": "From", "value": OWNER}]}
    api.threads["t-r"] = [theirs, mine]
    assert make(api).get_reply_recipient("t-r") == "recruiting@acme.example"
    api.threads["t-only-me"] = [mine]
    with pytest.raises(GmailNotFound):
        make(api).get_reply_recipient("t-only-me")


def decoded(raw: str) -> tuple[object, bytes]:
    message = message_from_bytes(base64.urlsafe_b64decode(raw), policy=default)
    return message, message.get_body().get_content().encode()  # type: ignore[union-attr]


def test_us65_draft_is_created_in_the_thread_with_reply_headers_and_recipient(
    api: FakeGmailApi,
) -> None:
    request = DraftRequest(
        "t-interview", "<b@x>", "<a@x> <b@x>", "Re: Interview", "Hello, thanks.\n", "hr@globex.test"
    )
    ref = make(api).create_draft(request)
    body = api.drafts[ref.draft_id]
    assert body["message"]["threadId"] == "t-interview"
    message, content = decoded(body["message"]["raw"])
    assert message["To"] == "hr@globex.test"  # type: ignore[index]
    assert message["Subject"] == "Re: Interview"  # type: ignore[index]
    assert message["In-Reply-To"] == "<b@x>"  # type: ignore[index]
    assert message["References"] == "<a@x> <b@x>"  # type: ignore[index]
    assert message["Content-Type"].startswith("text/plain") and "utf-8" in message["Content-Type"]  # type: ignore[index]
    assert content.strip() == b"Hello, thanks."
    assert make(api).get_draft(ref.draft_id) == ref


def test_us65_draft_headers_are_stripped_of_crlf_and_nul_injection() -> None:
    request = DraftRequest(
        "t",
        "<a@x>\r\nBcc: evil@x.test",
        "<a@x>\nX-Evil: 1",
        "Re: Hi\r\nBcc: evil@x.test",
        "Body",
        "to@x.test",
    )
    raw = base64.urlsafe_b64decode(build_raw_message(request))
    head = raw.replace(b"\r\n", b"\n").split(b"\n\n")[0]
    names = [line.split(b":")[0].lower() for line in head.split(b"\n") if line[:1] not in b" \t"]
    assert names == [b"to", b"subject", b"in-reply-to", b"references", b"content-type"] + [
        n for n in names[5:] if n.startswith(b"mime") or n.startswith(b"content")
    ]
    assert b"\x00" not in raw and b"bcc" not in b"".join(names) and b"x-evil" not in b"".join(names)


def test_us65_non_ascii_headers_are_rfc2047_and_body_is_utf8() -> None:
    request = DraftRequest("t", "<a@x>", "<a@x>", "Re: Café à Zürich", "Grüße, 你好", "to@x.test")
    raw = base64.urlsafe_b64decode(build_raw_message(request))
    header_block = raw.split(b"\n\n")[0] if b"\n\n" in raw else raw.split(b"\r\n\r\n")[0]
    assert header_block.isascii() and b"=?utf-8?" in header_block.lower()
    message, content = decoded(build_raw_message(request))
    assert str(make_header(decode_header(str(message["Subject"])))) == "Re: Café à Zürich"  # type: ignore[index]
    assert content.decode().strip() == "Grüße, 你好"


# ---- access tokens and revoke ----


def test_us31_access_token_cache_is_shared_per_user_and_expires(api: FakeGmailApi) -> None:
    cache = AccessTokenCache()
    user = uuid.uuid4()
    http = httpx.Client(transport=api.transport())
    clock = {"now": NOW}
    provider = CachedAccessTokens(user, REFRESH_TOKEN, CONFIG, http, cache, lambda: clock["now"])
    first = provider()
    assert provider() == first and api.refresh_count == 1
    clock["now"] = NOW + timedelta(seconds=3600 - 30)  # inside the 60 second skew
    assert provider() != first and api.refresh_count == 2


def test_us31_access_token_is_never_in_repr_or_error_text(api: FakeGmailApi) -> None:
    http = httpx.Client(transport=api.transport())
    token = refresh_access_token(REFRESH_TOKEN, CONFIG, http, lambda: NOW)
    assert token.token not in repr(token) and token.scopes == "gmail.readonly"
    api.refresh_error = "invalid_grant"
    with pytest.raises(GmailAuthRevoked) as raised:
        refresh_access_token(REFRESH_TOKEN, CONFIG, http, lambda: NOW)
    assert REFRESH_TOKEN not in str(raised.value)


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (200, {}, RevokeResult.OK),
        (400, {"error": "invalid_token"}, RevokeResult.ALREADY_INVALID),
        (400, {"error": "invalid_request"}, RevokeResult.FAILED),
        (500, {}, RevokeResult.FAILED),
    ],
)
def test_us35_revoker_maps_google_responses(
    api: FakeGmailApi, status: int, body: dict[str, object], expected: RevokeResult
) -> None:
    api.revoke_status, api.revoke_body = status, body
    revoker = GoogleTokenRevoker(httpx.Client(transport=api.transport()), REVOKE_URL)
    assert revoker.revoke(REFRESH_TOKEN) is expected
    sent = [r for r in api.requests if str(r.url) == REVOKE_URL]
    assert sent[0].content == f"token={REFRESH_TOKEN.replace('/', '%2F')}".encode()


def test_us35_revoker_network_failure_is_failed() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    revoker = GoogleTokenRevoker(httpx.Client(transport=httpx.MockTransport(boom)), REVOKE_URL)
    assert revoker.revoke("t") is RevokeResult.FAILED


SEPARATORS = [
    "\r",
    "\n",
    "\x00",
    "\x0b",
    "\x0c",
    "\x1c",
    "\x1d",
    "\x1e",
    "\x85",
    "\u2028",
    "\u2029",
]


@pytest.mark.parametrize("sep", SEPARATORS)
@pytest.mark.parametrize("field", ["subject", "references", "in_reply_to"])
def test_us65_every_line_separator_is_stripped_from_headers(sep: str, field: str) -> None:
    values = {"subject": "Re: Hi", "references": "<a@x>", "in_reply_to": "<a@x>"}
    values[field] = f"{values[field]}{sep}X-Evil: 1"
    request = DraftRequest(
        "t", values["in_reply_to"], values["references"], values["subject"], "B", "to@x.test"
    )
    raw = base64.urlsafe_b64decode(build_raw_message(request)).decode("ascii")
    head = raw.replace("\r\n", "\n").split("\n\n")[0]
    assert not any(line.lower().startswith("x-evil") for line in head.split("\n"))
    assert len(head.splitlines()) == len(head.split("\n"))  # no hidden separators left


@pytest.mark.parametrize("sep", SEPARATORS)
def test_us65_separator_in_the_recipient_cannot_add_headers_or_addresses(sep: str) -> None:
    request = DraftRequest("t", "<a@x>", "<a@x>", "S", "B", f"to@x.test{sep}Bcc: e@x.test")
    with pytest.raises(GmailError):
        build_raw_message(request)


@pytest.mark.parametrize(
    "to",
    [
        "a@b.com, c@d.com",
        "a@b.com; c@d.com",
        "a@b.com c@d.com",
        '"a@b.com, c@d.com"@x.com',
        '"a@b.com"@x.com',
        "a@b@c.com",
        "<a@b.com><c@d.com>",
        "a",
        "",
        "@b.com",
        "a@",
    ],
)
def test_us65_invalid_recipients_are_refused(to: str) -> None:
    with pytest.raises(GmailError, match="invalid_recipient"):
        build_raw_message(DraftRequest("t", "<a@x>", "<a@x>", "S", "B", to))


def test_us65_a_display_name_is_dropped_and_only_the_address_is_used() -> None:
    request = DraftRequest("t", "<a@x>", "<a@x>", "S", "B", "Dana Smith <dana@acme.example>")
    message, _ = decoded(build_raw_message(request))
    assert message["To"] == "dana@acme.example"  # type: ignore[index]


def test_us65_references_are_capped_to_the_newest_ids() -> None:
    many = " ".join(f"<m{i}@x>" for i in range(50))
    capped = cap_references(many).split()
    assert capped == [f"<m{i}@x>" for i in range(30, 50)]
    long_ids = " ".join(f"<{'a' * 150}{i}@x>" for i in range(20))
    result = cap_references(long_ids)
    assert len(result) <= 2000 and result.endswith(f"{'a' * 150}19@x>")
