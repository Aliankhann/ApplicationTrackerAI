"""Gmail REST client behind the `GmailClient` protocol.

Metadata only: threads are fetched with `format=metadata` and a fixed header allowlist, never
`full` or `raw`, and no body is ever parsed. Nothing here logs; error messages are constants.

Batch fetching: `get_threads` issues individual `threads.get` calls from a small thread pool
(at most `MAX_CONCURRENCY` in flight) instead of Gmail's multipart batch endpoint. That keeps
error mapping per request and the code small; 50 ids per batch (the sync's batch size) is well
inside Gmail's per-user concurrency limits.
"""

import html
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from email.header import decode_header, make_header
from email.utils import parseaddr
from typing import Any, NoReturn

import httpx

from app.providers.gmail.draft_message import build_raw_message
from app.providers.gmail.errors import (
    GmailAuthRevoked,
    GmailError,
    GmailHistoryExpired,
    GmailNotFound,
    GmailRateLimited,
)
from app.providers.gmail.types import (
    DraftRef,
    DraftRequest,
    HistoryPage,
    MessageMeta,
    Profile,
    ThreadMeta,
    ThreadSummary,
)

BASE_URL = "https://gmail.googleapis.com/gmail/v1/users/me"
MAX_CONCURRENCY = 5
PAGE_SIZE = 100
TIMEOUT = httpx.Timeout(20.0, connect=5.0)
METADATA_HEADERS = ("From", "Subject", "Message-ID", "References", "In-Reply-To")
RECIPIENT_HEADERS = ("From", "Reply-To")
RATE_REASONS = frozenset(
    {"rateLimitExceeded", "userRateLimitExceeded", "dailyLimitExceeded", "quotaExceeded"}
)

# `provider(force_refresh)` returns a bearer token; True means the cached one was rejected.
AccessTokenProvider = Callable[[bool], str]
Params = list[tuple[str, str | int | float | bool | None]]


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return max(0.0, float(response.headers["Retry-After"]))
    except (KeyError, ValueError):
        return None


def _forbidden_is_rate_limit(response: httpx.Response) -> bool:
    try:
        error = response.json()["error"]
        reasons = {str(item.get("reason")) for item in error.get("errors", [])}
        return bool(reasons & RATE_REASONS) or error.get("status") == "RESOURCE_EXHAUSTED"
    except (ValueError, KeyError, TypeError, AttributeError):
        return False


def _decode(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except (ValueError, UnicodeError):
        return value


def _headers_of(message: dict[str, Any]) -> dict[str, str]:
    items = message.get("payload", {}).get("headers", [])
    return {str(h["name"]).lower(): str(h["value"]) for h in items if "name" in h and "value" in h}


def _sent_at(message: dict[str, Any]) -> datetime:
    try:
        return datetime.fromtimestamp(int(message["internalDate"]) / 1000, tz=UTC)
    except (KeyError, ValueError, TypeError, OverflowError, OSError):
        raise GmailError("malformed message") from None


class RestGmailClient:
    def __init__(self, access_token_provider: AccessTokenProvider, http: httpx.Client) -> None:
        self._tokens = access_token_provider
        self._http = http
        self._owner_email: str | None = None

    # -- transport ----------------------------------------------------------------------------

    def _get(self, path: str, params: Params | None = None, *, missing: type[GmailError]) -> Any:
        return self._call("GET", path, params, None, missing)

    def _call(
        self,
        method: str,
        path: str,
        params: Params | None,
        body: dict[str, Any] | None,
        missing: type[GmailError] = GmailNotFound,
    ) -> Any:
        for force_refresh in (False, True):
            token = self._tokens(force_refresh)
            try:
                response = self._http.request(
                    method,
                    f"{BASE_URL}{path}",
                    params=params,
                    json=body,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=TIMEOUT,
                )
            except httpx.HTTPError:
                raise GmailError("gmail request failed") from None
            if response.status_code != 401:
                return self._parse(response, missing)
        raise GmailAuthRevoked  # still 401 with a freshly refreshed token

    def _parse(self, response: httpx.Response, missing: type[GmailError]) -> Any:
        status = response.status_code
        if status < 400:
            try:
                return response.json()
            except ValueError:
                raise GmailError("malformed response") from None
        self._raise_for(response, missing)

    def _raise_for(self, response: httpx.Response, missing: type[GmailError]) -> NoReturn:
        status = response.status_code
        if status == 404:
            raise missing("not found")
        if status == 429 or status >= 500:
            raise GmailRateLimited(_retry_after(response))
        if status == 403 and _forbidden_is_rate_limit(response):
            raise GmailRateLimited(_retry_after(response))
        raise GmailError(f"gmail request rejected ({status})")

    # -- GmailClient --------------------------------------------------------------------------

    def get_profile(self) -> Profile:
        data = self._get("/profile", missing=GmailNotFound)
        try:
            profile = Profile(email=str(data["emailAddress"]), history_id=str(data["historyId"]))
        except (KeyError, TypeError):
            raise GmailError("malformed response") from None
        self._owner_email = profile.email.lower()
        return profile

    def _owner(self) -> str:
        if self._owner_email is None:
            return self.get_profile().email.lower()
        return self._owner_email

    def list_threads(
        self, query: str, page_token: str | None = None
    ) -> tuple[list[ThreadSummary], str | None]:
        params: Params = [("q", query), ("maxResults", str(PAGE_SIZE))]
        if page_token:
            params.append(("pageToken", page_token))
        data = self._get("/threads", params, missing=GmailNotFound)
        try:
            threads = [
                ThreadSummary(str(t["id"]), str(t.get("historyId", ""))) for t in data["threads"]
            ]
        except KeyError:
            threads = []  # Gmail omits the key when nothing matches
        except TypeError:
            raise GmailError("malformed response") from None
        return threads, data.get("nextPageToken") or None

    def get_thread(self, thread_id: str) -> ThreadMeta:
        owner = self._owner()
        params: Params = [("format", "metadata")]
        params += [("metadataHeaders", name) for name in METADATA_HEADERS]
        data = self._get(f"/threads/{thread_id}", params, missing=GmailNotFound)
        return self._thread(data, owner)

    def get_threads(self, thread_ids: list[str]) -> list[ThreadMeta]:
        """Raises GmailNotFound (or the first error, in id order) if any fetch fails."""
        self._owner()  # warm the profile and access token once, not once per worker
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as pool:
            futures = [pool.submit(self.get_thread, thread_id) for thread_id in thread_ids]
            return [future.result() for future in futures]

    def list_history(self, start_history_id: str, page_token: str | None = None) -> HistoryPage:
        params: Params = [("startHistoryId", start_history_id), ("historyTypes", "messageAdded")]
        if page_token:
            params.append(("pageToken", page_token))
        data = self._get("/history", params, missing=GmailHistoryExpired)
        try:
            ids: dict[str, None] = {}
            for record in data.get("history", []):
                for added in record.get("messagesAdded", []):
                    ids[str(added["message"]["threadId"])] = None
            return HistoryPage(
                history_id=str(data["historyId"]),
                changed_thread_ids=tuple(ids),
                next_page_token=data.get("nextPageToken") or None,
            )
        except (KeyError, TypeError, AttributeError):
            raise GmailError("malformed response") from None

    def get_reply_recipient(self, thread_id: str) -> str:
        """Reply-To (else From) of the last message from someone else. Never stored."""
        owner = self._owner()
        params: Params = [("format", "metadata")]
        params += [("metadataHeaders", name) for name in RECIPIENT_HEADERS]
        data = self._get(f"/threads/{thread_id}", params, missing=GmailNotFound)
        for message in reversed(data.get("messages", [])):
            headers = _headers_of(message)
            sender = parseaddr(headers.get("from", ""))[1]
            if sender and sender.lower() != owner:
                return parseaddr(headers.get("reply-to", ""))[1] or sender
        raise GmailNotFound("no recipient")

    def create_draft(self, request: DraftRequest) -> DraftRef:
        body = {"message": {"raw": build_raw_message(request), "threadId": request.thread_id}}
        data = self._call("POST", "/drafts", None, body)
        try:
            return DraftRef(str(data["id"]))
        except (KeyError, TypeError):
            raise GmailError("malformed response") from None

    def get_draft(self, draft_id: str) -> DraftRef | None:
        try:
            data = self._get(f"/drafts/{draft_id}", [("format", "minimal")], missing=GmailNotFound)
        except GmailNotFound:
            return None
        try:
            return DraftRef(str(data["id"]))
        except (KeyError, TypeError):
            raise GmailError("malformed response") from None

    # -- parsing ------------------------------------------------------------------------------

    def _thread(self, data: dict[str, Any], owner: str) -> ThreadMeta:
        try:
            raw_messages = list(data["messages"])
            thread_id, history_id = str(data["id"]), str(data["historyId"])
        except (KeyError, TypeError):
            raise GmailNotFound("empty thread") from None
        try:
            messages = sorted(
                (self._message(m, owner) for m in raw_messages), key=lambda m: m.sent_at
            )
        except (KeyError, TypeError, AttributeError):
            raise GmailError("malformed response") from None
        if not messages:
            raise GmailNotFound("empty thread")
        return ThreadMeta(thread_id, history_id, tuple(messages))

    def _message(self, message: dict[str, Any], owner: str) -> MessageMeta:
        headers = _headers_of(message)
        name, address = parseaddr(_decode(headers.get("from", "")))
        return MessageMeta(
            message_id=str(message["id"]),
            thread_id=str(message["threadId"]),
            from_address=address,
            from_name=name,
            subject=_decode(headers.get("subject", "")),
            snippet=html.unescape(str(message.get("snippet", ""))),
            sent_at=_sent_at(message),
            from_user=address.lower() == owner,
            rfc822_message_id=headers.get("message-id"),
            label_ids=frozenset(str(label) for label in message.get("labelIds", [])),
        )
