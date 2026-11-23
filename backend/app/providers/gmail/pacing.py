"""Quota-aware pacing for the Gmail REST client.

Gmail charges "quota units" per call against a per-user, per-second budget. Every request first
takes its cost from a token bucket, so a burst is bounded by one second of budget and the
sustained rate never exceeds it, however many threads share the client.

The costs below are CONSERVATIVE ESTIMATES. Verify them against Google's published Gmail API
quota table (developers.google.com/gmail/api/reference/quota) and adjust here, in one place.
"""

import threading
import time
from collections.abc import Callable

UNIT_COSTS: dict[str, int] = {
    "threads.get": 10,
    "threads.list": 10,
    "history.list": 2,
    "profile.get": 1,
    "drafts.create": 10,
    "drafts.get": 5,
}


class TokenBucket:
    """Thread-safe. Capacity is one second of budget; the bucket starts full.

    `acquire` reserves its cost immediately (the balance may go negative) and sleeps, outside the
    lock, until the reservation is paid for, so concurrent callers queue fairly.
    """

    def __init__(
        self,
        units_per_second: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if units_per_second <= 0:
            raise ValueError("units_per_second must be positive")
        self._rate = units_per_second
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._balance = units_per_second
        self._last = clock()

    def acquire(self, cost: float) -> None:
        with self._lock:
            now = self._clock()
            self._balance = min(self._rate, self._balance + (now - self._last) * self._rate)
            self._last = now
            self._balance -= cost
            wait = -self._balance / self._rate if self._balance < 0 else 0.0
        if wait > 0:
            self._sleep(wait)
