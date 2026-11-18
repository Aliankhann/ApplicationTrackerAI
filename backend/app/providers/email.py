"""Transactional email behind an interface. The real provider (Resend/Postmark) is not wired yet."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol


class EmailSendError(Exception):
    """The provider did not accept the message. Carries a stable code, never message content."""

    def __init__(self, code: str = "send_failed") -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class OutgoingEmail:
    to_address: str
    subject: str
    text: str
    html: str
    headers: Mapping[str, str] = field(default_factory=dict)


class EmailSender(Protocol):
    def send_deletion_confirmation(self, to_address: str) -> None: ...

    def send(self, message: OutgoingEmail) -> None:
        """Raises EmailSendError when the message was not accepted."""
        ...


class UnconfiguredEmailSender:
    """Outside local until a provider is wired: fails closed, never recorded as sent."""

    def send_deletion_confirmation(self, to_address: str) -> None:
        raise EmailSendError("not_configured")

    def send(self, message: OutgoingEmail) -> None:
        raise EmailSendError("not_configured")


class ConsoleEmailSender:
    """Local development: prints the rendered email. Only ever constructed for environment local."""

    def send_deletion_confirmation(self, to_address: str) -> None:
        print(f"[email] deletion confirmation to {to_address}")

    def send(self, message: OutgoingEmail) -> None:
        lines = [f"To: {message.to_address}", f"Subject: {message.subject}"]
        lines += [f"{name}: {value}" for name, value in message.headers.items()]
        print("[email]\n" + "\n".join(lines) + "\n\n" + message.text)


def sender_for(environment: str) -> EmailSender:
    return ConsoleEmailSender() if environment == "local" else UnconfiguredEmailSender()


class FakeEmailSender:
    def __init__(self) -> None:
        self.deletion_confirmations: list[str] = []
        self.sent: list[OutgoingEmail] = []
        self.fail_with: EmailSendError | None = None

    def send_deletion_confirmation(self, to_address: str) -> None:
        self.deletion_confirmations.append(to_address)

    def send(self, message: OutgoingEmail) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.sent.append(message)
