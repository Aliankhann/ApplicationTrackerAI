"""Revoking a refresh token at Google, behind an interface. Tests use the fake.

`GoogleTokenRevoker` is the real call; without Google config, production wiring raises
`RevokerNotConfigured`. Neither the token nor Google's response body is ever logged.
"""

from enum import StrEnum
from typing import Protocol

import httpx


class RevokeResult(StrEnum):
    OK = "ok"
    ALREADY_INVALID = "already_invalid"
    FAILED = "failed"


class RevokerNotConfigured(RuntimeError):
    """No real revoker is wired yet."""

    def __init__(self) -> None:
        super().__init__("token revoker is not configured")


class TokenRevoker(Protocol):
    def revoke(self, refresh_token: str) -> RevokeResult: ...


class UnconfiguredTokenRevoker:
    def revoke(self, refresh_token: str) -> RevokeResult:
        raise RevokerNotConfigured


class FakeTokenRevoker:
    """Records every call; `result` is what the next calls return."""

    def __init__(self, result: RevokeResult = RevokeResult.OK) -> None:
        self.result = result
        self.calls: list[str] = []

    def revoke(self, refresh_token: str) -> RevokeResult:
        self.calls.append(refresh_token)
        return self.result


class GoogleTokenRevoker:
    """POST the token to Google's revoke endpoint: 200 ok, 400 invalid_token already gone."""

    def __init__(self, http: httpx.Client, endpoint: str) -> None:
        self._http = http
        self._endpoint = endpoint

    def revoke(self, refresh_token: str) -> RevokeResult:
        try:
            response = self._http.post(
                self._endpoint, data={"token": refresh_token}, timeout=_TIMEOUT
            )
        except httpx.HTTPError:
            return RevokeResult.FAILED
        if response.status_code == 200:
            return RevokeResult.OK
        if response.status_code == 400 and _is_invalid_token(response):
            return RevokeResult.ALREADY_INVALID
        return RevokeResult.FAILED


_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


def _is_invalid_token(response: httpx.Response) -> bool:
    try:
        body = response.json()
    except ValueError:
        return False
    return isinstance(body, dict) and body.get("error") == "invalid_token"
