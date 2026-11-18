from collections.abc import Callable
from dataclasses import fields
from datetime import UTC, datetime, timedelta

import pytest

from app.providers.gmail import (
    DraftRequest,
    FakeGmailClient,
    GmailAuthRevoked,
    GmailClient,
    GmailError,
    GmailHistoryExpired,
    GmailNotFound,
    GmailRateLimited,
    MessageMeta,
)
from tests.fixtures.gmail_threads import OWNER, build_threads

NOW = datetime(2026, 6, 1, tzinfo=UTC)


def make(**kwargs: int) -> FakeGmailClient:
    return FakeGmailClient(OWNER, build_threads(NOW), now=NOW, **kwargs)


def test_fake_is_accepted_by_mypy_as_gmail_client() -> None:
    client: GmailClient = make()
    assert client.get_profile().email == OWNER


def test_list_threads_newer_than_filters_and_paginates_without_gaps() -> None:
    client = make(page_size=2)
    seen: list[str] = []
    token: str | None = None
    pages = 0
    while True:
        page, token = client.list_threads("newer_than:90d", token)
        seen += [t.thread_id for t in page]
        pages += 1
        if token is None:
            break
    assert pages == 2
    assert sorted(seen) == ["t-confirm", "t-interview", "t-reject", "t-sent"]
    assert len(seen) == len(set(seen))


def test_get_thread_chronological_with_sender_and_timestamps() -> None:
    client = make()
    client.add_message("t-sent", from_address="hr@x.example", sent_at=NOW)
    client.add_message("t-sent", from_address=OWNER, from_user=True, sent_at=NOW.replace(year=2025))
    thread = client.get_thread("t-sent")
    times = [m.sent_at for m in thread.messages]
    assert times == sorted(times)
    assert thread.message_count == 3
    assert thread.first_message_at == NOW.replace(year=2025)
    assert thread.last_message_at == NOW
    assert thread.last_sender_is_user is False
    assert thread.last_message.from_address == "hr@x.example"
    assert make().get_thread("t-sent").last_sender_is_user is True


def test_get_thread_unknown_id_raises_not_found() -> None:
    with pytest.raises(GmailNotFound):
        make().get_thread("nope")


def test_add_message_bumps_history_and_list_history_returns_changed_threads() -> None:
    client = make()
    before = client.get_profile().history_id
    client.add_message("t-confirm", from_address="a@x.example")
    client.add_message("t-new", from_address="b@x.example")
    client.add_message("t-new", from_address="b@x.example")
    assert int(client.get_profile().history_id) == int(before) + 3
    page = client.list_history(before)
    assert sorted(page.changed_thread_ids) == ["t-confirm", "t-new"]
    assert page.next_page_token is None
    assert client.list_history(page.history_id).changed_thread_ids == ()


def test_list_history_below_floor_raises_history_expired() -> None:
    client = make(history_floor=500)
    with pytest.raises(GmailHistoryExpired):
        client.list_history("499")


def test_revoke_makes_every_method_raise_auth_revoked() -> None:
    client = make()
    client.revoke()
    calls: list[Callable[[], object]] = [
        client.get_profile,
        lambda: client.list_threads("newer_than:1d"),
        lambda: client.get_thread("t-sent"),
        lambda: client.list_history("1"),
        lambda: client.get_reply_recipient("t-sent"),
        lambda: client.create_draft(DraftRequest("t", "<a>", "<a>", "s", "b")),
    ]
    for call in calls:
        with pytest.raises(GmailAuthRevoked):
            call()


def test_fail_next_raises_once_then_recovers() -> None:
    client = make()
    client.fail_next(GmailRateLimited(retry_after=2.0))
    with pytest.raises(GmailRateLimited) as info:
        client.get_profile()
    assert info.value.retry_after == 2.0
    assert client.get_profile().email == OWNER


def test_create_draft_records_request_and_returns_unique_ids() -> None:
    client = make()
    first = DraftRequest("t-sent", "<a@x>", "<a@x>", "Re: hi", "Thanks")
    second = DraftRequest("t-sent", "<b@x>", "<b@x>", "Re: hi", "Again")
    a, b = client.create_draft(first), client.create_draft(second)
    assert a.draft_id != b.draft_id
    assert client.drafts == (first, second)


def test_get_reply_recipient_returns_last_external_sender() -> None:
    client = make()
    assert client.get_reply_recipient("t-interview") == "hr@globex-labs.example"
    client.add_message("t-interview", from_address=OWNER, from_user=True)
    assert client.get_reply_recipient("t-interview") == "hr@globex-labs.example"


def test_message_meta_has_no_body_or_recipient_fields() -> None:
    assert {f.name for f in fields(MessageMeta)} == {
        "message_id",
        "thread_id",
        "from_address",
        "from_name",
        "subject",
        "snippet",
        "sent_at",
        "from_user",
        "rfc822_message_id",
        "label_ids",
    }


def test_naive_datetime_rejected_everywhere() -> None:
    naive = datetime(2026, 1, 9)
    with pytest.raises(ValueError):
        FakeGmailClient(OWNER, now=naive)
    with pytest.raises(ValueError):
        make().add_message("t", from_address="a@x.example", sent_at=naive)
    with pytest.raises(ValueError):
        MessageMeta("m", "t", "a@x.example", "", "", "", naive, False, None)


def test_empty_thread_rejected_in_constructor() -> None:
    with pytest.raises(ValueError):
        FakeGmailClient(OWNER, {"t": []}, now=NOW)


def test_bad_page_tokens_and_history_ids_raise_gmail_errors() -> None:
    client = make()
    with pytest.raises(GmailError):
        client.list_threads("x", "abc")
    with pytest.raises(GmailError):
        client.list_history("abc")
    with pytest.raises(GmailNotFound):
        client.list_history("999999")
    with pytest.raises(GmailNotFound):
        client.list_history("1000", "bad")


def test_list_threads_newest_first_with_id_tiebreak() -> None:
    client = FakeGmailClient(OWNER, now=NOW)
    client.add_message("b", from_address="a@x.example", sent_at=NOW - timedelta(days=3))
    client.add_message("a", from_address="a@x.example", sent_at=NOW - timedelta(days=1))
    client.add_message("c", from_address="a@x.example", sent_at=NOW - timedelta(days=1))
    assert [t.thread_id for t in client.list_threads("")[0]] == ["a", "c", "b"]


def test_create_draft_unknown_thread_raises_not_found() -> None:
    with pytest.raises(GmailNotFound):
        make().create_draft(DraftRequest("nope", "<a>", "<a>", "s", "b"))


def test_create_draft_adds_draft_message_bumps_history_and_maps_id() -> None:
    client = make()
    before = client.get_profile().history_id
    ref = client.create_draft(DraftRequest("t-sent", "<a>", "<a>", "s", "x" * 300))
    assert client.list_history(before).changed_thread_ids == ("t-sent",)
    last = client.get_thread("t-sent").last_message
    assert last.is_draft and last.from_user and len(last.snippet) == 200
    assert client.get_draft(ref.draft_id) == ref


def test_send_and_delete_draft_update_thread_and_draft_existence() -> None:
    client = make()
    sent = client.create_draft(DraftRequest("t-sent", "<a>", "<a>", "s", "b"))
    gone = client.create_draft(DraftRequest("t-sent", "<a>", "<a>", "s", "b"))
    client.send_draft(sent.draft_id)
    client.delete_draft(gone.draft_id)
    messages = client.get_thread("t-sent").messages
    assert [m.is_draft for m in messages] == [False, False]
    assert "SENT" in messages[-1].label_ids
    assert client.get_draft(sent.draft_id) is None
    assert client.get_draft(gone.draft_id) is None


def test_get_threads_batch_and_missing_id_raises_not_found() -> None:
    client = make()
    assert [t.thread_id for t in client.get_threads(["t-sent", "t-confirm"])] == [
        "t-sent",
        "t-confirm",
    ]
    with pytest.raises(GmailNotFound):
        client.get_threads(["t-sent", "nope"])


def test_list_history_pagination_stable_against_concurrent_adds() -> None:
    client = FakeGmailClient(OWNER, now=NOW, page_size=1)
    start = client.get_profile().history_id
    for tid in ("a", "b", "c"):
        client.add_message(tid, from_address="x@x.example")
    first = client.list_history(start)
    client.add_message("a", from_address="x@x.example")
    seen = list(first.changed_thread_ids)
    token = first.next_page_token
    while token:
        page = client.list_history(start, token)
        seen += page.changed_thread_ids
        token = page.next_page_token
    assert seen == ["a", "b", "c"]
