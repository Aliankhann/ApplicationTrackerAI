"""Revoking a refresh token at Google, behind an interface. Tests use the fake.

The real implementation arrives with US-31; until then production wiring raises
`RevokerNotConfigured`. Neither the token nor Google's response body is ever logged.
"""

from enum import StrEnum
from typing import Protocol


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
