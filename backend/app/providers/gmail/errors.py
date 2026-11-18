class GmailError(Exception):
    """Base class for Gmail provider failures."""


class GmailAuthRevoked(GmailError):
    """The user's grant is gone (Google invalid_grant)."""


class GmailHistoryExpired(GmailError):
    """The history id is too old; a full resync is needed."""


class GmailRateLimited(GmailError):
    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("Gmail rate limited")
        self.retry_after = retry_after


class GmailNotFound(GmailError):
    """The thread or message does not exist."""
