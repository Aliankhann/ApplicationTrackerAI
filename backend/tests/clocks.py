"""Fake clocks that advance on every read, for time-budget tests."""

from datetime import datetime, timedelta


class StepClock:
    """Returns the current time, then moves it forward by `step` seconds."""

    def __init__(self, start: datetime, step: float = 1.0) -> None:
        self.now = start
        self.step = timedelta(seconds=step)
        self.reads = 0

    def __call__(self) -> datetime:
        value = self.now
        self.now += self.step
        self.reads += 1
        return value
