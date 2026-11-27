"""Gmail REST client behind the `GmailClient` protocol.

Threads are fetched with `format=metadata` and a fixed header allowlist. The only `format=full`
call is `get_message_text`, which reads one message's text in memory for the caller (never
stored or logged here) and never requests attachments. Nothing here logs; error messages are
constants.

Batch fetching: `get_threads` issues individual `threads.get` calls from a small thread pool
(`max_concurrency` in flight) instead of Gmail's multipart batch endpoint. Every request first
takes its quota cost from a token bucket (`pacing.py`), so the pool cannot exceed the per-user
per-second budget. Threads that are rate limited are retried alone, with backoff; threads already
fetched are never fetched again.
"""

import html
import random
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from email.header import decode_header, make_header
from email.utils import parseaddr
from typing import Any, NoReturn

import httpx

from app.providers.gmail.body import message_text
from app.providers.gmail.draft_message import build_raw_message
from app.providers.gmail.errors import (
    GmailAuthRevoked,
    GmailError,
    GmailHistoryExpired,
    GmailNotFound,
    GmailRateLimited,
)
from app.providers.gmail.pacing import UNIT_COSTS, TokenBucket
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
MAX_CONCURRENCY = 2
THREAD_FETCH_ATTEMPTS = 4  # one try plus three rate-limit retries of the failed threads
RETRY_BASE_SECONDS = 1.0
RETRY_CAP_SECONDS = 8.0
PAGE_SIZE = 100
TIMEOUT = httpx.Timeout(20.0, connect=5.0)
METADATA_HEADERS = ("From", "Subject", "Message-ID", "References", "In-Reply-To")
RECIPIENT_HEADERS = ("From", "Reply-To")
MESSAGE_FIELDS = "payload(mimeType,filename,headers,body/data,parts)"  # no ids, labels, snippet
RATE_REASONS = frozenset(
    {"rateLimitExceeded", "userRateLimitExceeded", "dailyLimitExceeded", "quotaExceeded"}
)

# `provider(force_refresh)` returns a bearer token; True means the cached one was rejected.
AccessTokenProvider = Callable[[bool], str]
TimeLeft = Callable[[], float | None]  # seconds left in the caller's budget; None: unlimited
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
    def __init__(
        self,
        access_token_provider: AccessTokenProvider,
        http: httpx.Client,
        *,
        bucket: TokenBucket | None = None,
        max_concurrency: int = MAX_CONCURRENCY,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._tokens = access_token_provider
        self._http = http
        self._owner_email: str | None = None
        self._bucket = bucket or TokenBucket(100.0)
        self._max_concurrency = max_concurrency
        self._sleep = sleep
        self._jitter = jitter
        self._hits_lock = threading.Lock()
        self.rate_limit_hits = 0

    # -- transport ----------------------------------------------------------------------------

    def _get(
        self, op: str, path: str, params: Params | None = None, *, missing: type[GmailError]
    ) -> Any:
        return self._call(op, "GET", path, params, None, missing)

    def _call(
        self,
        op: str,
        method: str,
        path: str,
        params: Params | None,
        body: dict[str, Any] | None,
        missing: type[GmailError] = GmailNotFound,
    ) -> Any:
        for force_refresh in (False, True):
            token = self._tokens(force_refresh)
            self._bucket.acquire(UNIT_COSTS[op])
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
        if status == 429 or status >= 500 or (status == 403 and _forbidden_is_rate_limit(response)):
            with self._hits_lock:
                self.rate_limit_hits += 1
            raise GmailRateLimited(_retry_after(response))
        raise GmailError(f"gmail request rejected ({status})")

    # -- GmailClient --------------------------------------------------------------------------

    def get_profile(self) -> Profile:
        data = self._get("profile.get", "/profile", missing=GmailNotFound)
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
        data = self._get("threads.list", "/threads", params, missing=GmailNotFound)
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
        data = self._get("threads.get", f"/threads/{thread_id}", params, missing=GmailNotFound)
        return self._thread(data, owner)

    def get_threads(
        self, thread_ids: list[str], time_left: TimeLeft | None = None
    ) -> list[ThreadMeta]:
        """Fetch in id order; threads that no longer exist are left out. Only rate-limited threads
        are retried (Retry-After, else full-jitter backoff). `time_left` (seconds, or None for
        unlimited) bounds the retries: a delay longer than the time left is not slept, the call
        gives up at once. Raises GmailRateLimited carrying the threads fetched if some stay rate
        limited, or the first other error in id order."""
        self._owner()  # warm the profile and access token once, not once per worker
        done: dict[str, ThreadMeta] = {}
        pending = list(thread_ids)
        hint: float | None = None
        for attempt in range(THREAD_FETCH_ATTEMPTS):
            if attempt:
                delay = self._retry_delay(attempt - 1, hint)
                left = time_left() if time_left else None
                if left is not None and left <= delay:
                    break
                self._sleep(delay)
            outcomes = self._fetch_round(pending)
            pending, hint = [], None
            for thread_id, outcome in outcomes.items():
                if isinstance(outcome, GmailRateLimited):
                    pending.append(thread_id)
                    hint = max(hint or 0.0, outcome.retry_after or 0.0) or None
                elif isinstance(outcome, GmailNotFound):
                    continue  # deleted since it was listed
                elif isinstance(outcome, GmailError):
                    raise outcome
                else:
                    done[thread_id] = outcome
            if not pending:
                return [done[t] for t in thread_ids if t in done]
        raise GmailRateLimited(hint, tuple(done[t] for t in thread_ids if t in done))

    def _fetch_round(self, thread_ids: list[str]) -> dict[str, ThreadMeta | GmailError]:
        def fetch(thread_id: str) -> ThreadMeta | GmailError:
            try:
                return self.get_thread(thread_id)
            except GmailError as exc:
                return exc

        with ThreadPoolExecutor(max_workers=self._max_concurrency) as pool:
            return dict(zip(thread_ids, pool.map(fetch, thread_ids), strict=True))

    def _retry_delay(self, retry: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(retry_after, RETRY_CAP_SECONDS)
        return float(self._jitter() * min(RETRY_CAP_SECONDS, RETRY_BASE_SECONDS * 2**retry))

    def list_history(self, start_history_id: str, page_token: str | None = None) -> HistoryPage:
        params: Params = [("startHistoryId", start_history_id), ("historyTypes", "messageAdded")]
        if page_token:
            params.append(("pageToken", page_token))
        data = self._get("history.list", "/history", params, missing=GmailHistoryExpired)
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

    def get_message_text(self, message_id: str, max_chars: int = 8000) -> str:
        """Readable text of one message (plain text, else HTML stripped), at most `max_chars`."""
        data = self._get(
            "messages.get",
            f"/messages/{message_id}",
            [("format", "full"), ("fields", MESSAGE_FIELDS)],
            missing=GmailNotFound,
        )
        try:
            return message_text(data.get("payload"), max_chars)
        except (AttributeError, TypeError):
            raise GmailError("malformed response") from None

    def get_reply_recipient(self, thread_id: str) -> str:
        """Reply-To (else From) of the last message from someone else. Never stored."""
        owner = self._owner()
        params: Params = [("format", "metadata")]
        params += [("metadataHeaders", name) for name in RECIPIENT_HEADERS]
        data = self._get("threads.get", f"/threads/{thread_id}", params, missing=GmailNotFound)
        for message in reversed(data.get("messages", [])):
            headers = _headers_of(message)
            sender = parseaddr(headers.get("from", ""))[1]
            if sender and sender.lower() != owner:
                return parseaddr(headers.get("reply-to", ""))[1] or sender
        raise GmailNotFound("no recipient")

    def create_draft(self, request: DraftRequest) -> DraftRef:
        body = {"message": {"raw": build_raw_message(request), "threadId": request.thread_id}}
        data = self._call("drafts.create", "POST", "/drafts", None, body)
        try:
            return DraftRef(str(data["id"]))
        except (KeyError, TypeError):
            raise GmailError("malformed response") from None

    def get_draft(self, draft_id: str) -> DraftRef | None:
        try:
            data = self._get(
                "drafts.get", f"/drafts/{draft_id}", [("format", "minimal")], missing=GmailNotFound
            )
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
