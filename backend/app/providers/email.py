"""Transactional email behind an interface. The real sender arrives with US-71."""

from typing import Protocol


class EmailSender(Protocol):
    def send_deletion_confirmation(self, to_address: str) -> None: ...


class NoopEmailSender:
    """Production stand-in until US-71: sends nothing."""

    def send_deletion_confirmation(self, to_address: str) -> None:
        return None


class FakeEmailSender:
    def __init__(self) -> None:
        self.deletion_confirmations: list[str] = []

    def send_deletion_confirmation(self, to_address: str) -> None:
        self.deletion_confirmations.append(to_address)
