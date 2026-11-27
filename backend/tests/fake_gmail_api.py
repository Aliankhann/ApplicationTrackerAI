"""A local stand-in for Google's Gmail REST API, token refresh, and revoke endpoints, served
through httpx.MockTransport. Synthetic data only; records every request for assertions."""

import html
import json
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.providers.gmail.types import MessageMeta
from tests.fake_google import CLIENT_ID, CLIENT_SECRET, TOKEN_URL

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
REFRESH_TOKEN = "1//synthetic-refresh-token"  # noqa: S105


def api_message(m: MessageMeta) -> dict[str, Any]:
    """The metadata-format JSON Gmail returns for one message (snippet is HTML-escaped)."""
    sender = f"{m.from_name} <{m.from_address}>" if m.from_name else m.from_address
    headers = [{"name": "From", "value": sender}, {"name": "Subject", "value": m.subject}]
    if m.rfc822_message_id:
        headers.append({"name": "Message-ID", "value": m.rfc822_message_id})
    return {
        "id": m.message_id,
        "threadId": m.thread_id,
        "labelIds": sorted(m.label_ids),
        "snippet": html.escape(m.snippet),
        "internalDate": str(int(m.sent_at.timestamp() * 1000)),
        "payload": {"headers": headers},
    }


@dataclass
class FakeGmailApi:
    owner: str
    threads: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    history_id: int = 5000
    page_size: int = 2
    requests: list[httpx.Request] = field(default_factory=list)
    errors: dict[str, tuple[int, dict[str, Any], dict[str, str]]] = field(default_factory=dict)
    refresh_error: str | None = None
    refresh_count: int = 0
    revoke_status: int = 200
    revoke_body: dict[str, Any] = field(default_factory=dict)
    drafts: dict[str, dict[str, Any]] = field(default_factory=dict)
    delay: float = 0.0
    reject_all: bool = False  # 401 even for freshly issued tokens
    valid_token: str = "at-0"  # noqa: S105
    in_flight: int = 0
    max_in_flight: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)
    payloads: dict[str, dict[str, Any]] = field(default_factory=dict)  # message id -> full payload
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def from_metas(cls, owner: str, threads: dict[str, list[MessageMeta]]) -> "FakeGmailApi":
        return cls(owner, {t: [api_message(m) for m in ms] for t, ms in threads.items()})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def expire_access_token(self) -> None:
        self.valid_token = "expired"  # noqa: S105

    def fail(
        self, path_prefix: str, status: int, body: dict[str, Any] | None = None, **hdr: str
    ) -> None:
        self.errors[path_prefix] = (status, body or {}, hdr)

    def gmail_urls(self) -> list[httpx.URL]:
        return [r.url for r in self.requests if str(r.url).startswith(GMAIL)]

    def handler(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            self.requests.append(request)
        url = str(request.url).split("?")[0]
        if url == TOKEN_URL:
            return self._refresh(request)
        if url == REVOKE_URL:
            return httpx.Response(self.revoke_status, json=self.revoke_body)
        if not url.startswith(GMAIL):
            return httpx.Response(404)
        if self.reject_all or request.headers.get("authorization") != f"Bearer {self.valid_token}":
            return httpx.Response(401, json={"error": {"code": 401}})
        path = url[len(GMAIL) :]
        for prefix, (status, body, headers) in self.errors.items():
            if path.startswith(prefix):
                return httpx.Response(status, json=body, headers=headers)
        return self._gmail(request, path)

    def _refresh(self, request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in urllib.parse.parse_qs(request.content.decode()).items()}
        ok = (
            form.get("grant_type") == "refresh_token"
            and form.get("client_id") == CLIENT_ID
            and form.get("client_secret") == CLIENT_SECRET
            and form.get("refresh_token") == REFRESH_TOKEN
        )
        if self.refresh_error or not ok:
            return httpx.Response(400, json={"error": self.refresh_error or "invalid_grant"})
        self.refresh_count += 1
        self.valid_token = f"at-{self.refresh_count}"
        body = {"access_token": self.valid_token, "expires_in": 3600, "scope": "gmail.readonly"}
        return httpx.Response(200, json=body)

    def _gmail(self, request: httpx.Request, path: str) -> httpx.Response:
        query = request.url.params
        with self._lock:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.delay:
                time.sleep(self.delay)
            return self._route(request, path, query)
        finally:
            with self._lock:
                self.in_flight -= 1

    def _route(self, request: httpx.Request, path: str, query: httpx.QueryParams) -> httpx.Response:
        if path == "/profile":
            return self._json({"emailAddress": self.owner, "historyId": str(self.history_id)})
        if path == "/threads":
            return self._list(query)
        if path.startswith("/threads/"):
            thread = self.threads.get(path.split("/")[2])
            if thread is None:
                return httpx.Response(404, json={"error": {"code": 404}})
            return self._json({"id": path.split("/")[2], "historyId": "42", "messages": thread})
        if path.startswith("/messages/"):
            return self._message(path.split("/")[2], query)
        if path == "/history":
            return self._json(self._history(query))
        if path == "/drafts" and request.method == "POST":
            body = json.loads(request.content)
            draft_id = f"d-{len(self.drafts) + 1}"
            self.drafts[draft_id] = body
            return self._json({"id": draft_id, "message": {"id": "m", "threadId": "t"}})
        if path.startswith("/drafts/"):
            draft_id = path.split("/")[2]
            if draft_id not in self.drafts:
                return httpx.Response(404, json={"error": {"code": 404}})
            return self._json({"id": draft_id})
        return httpx.Response(404)

    def _message(self, message_id: str, query: httpx.QueryParams) -> httpx.Response:
        payload = self.payloads.get(message_id)
        if payload is None or query.get("format") != "full":
            return httpx.Response(404, json={"error": {"code": 404}})
        return self._json({"id": message_id, "threadId": "t", "payload": payload})

    def _json(self, body: dict[str, Any]) -> httpx.Response:
        return httpx.Response(200, json=body)

    def _list(self, query: httpx.QueryParams) -> httpx.Response:
        ids = sorted(self.threads)
        start = int(query.get("pageToken", "0"))
        page = ids[start : start + self.page_size]
        body: dict[str, Any] = {"resultSizeEstimate": len(ids)}
        if page:
            body["threads"] = [{"id": t, "historyId": "7", "snippet": "x"} for t in page]
        if start + self.page_size < len(ids):
            body["nextPageToken"] = str(start + self.page_size)
        return self._json(body)

    def _history(self, query: httpx.QueryParams) -> dict[str, Any]:
        start = int(query.get("pageToken", "0"))
        page = self.history[start : start + 1]
        body: dict[str, Any] = {"history": page, "historyId": str(self.history_id)}
        if start + 1 < len(self.history):
            body["nextPageToken"] = str(start + 1)
        return body
