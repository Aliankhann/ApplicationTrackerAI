"""A wall-clock budget for one serverless invocation, split into shares per job part."""

from collections.abc import Callable
from datetime import datetime, timedelta

STOP_MARGIN_SECONDS = 20.0  # headroom for the last batch, the response, and cold-start slack


class Budget:
    """`total_seconds` from construction, less a safety margin. A part stops starting new work
    once its cumulative `share` (0..1) of the usable time has passed; unused time rolls over to
    the parts after it. `tripped` records that some part stopped early."""

    def __init__(self, clock: Callable[[], datetime], total_seconds: float) -> None:
        self.clock = clock
        self.start = clock()
        self.usable = timedelta(seconds=max(total_seconds - STOP_MARGIN_SECONDS, 0.0))
        self.tripped = False

    def stop_at(self, share: float) -> datetime:
        return self.start + self.usable * share

    def should_stop(self, share: float = 1.0) -> Callable[[], bool]:
        def check() -> bool:
            if self.clock() >= self.stop_at(share):
                self.tripped = True
                return True
            return False

        return check
