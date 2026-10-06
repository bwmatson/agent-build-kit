"""Durations of a unit's time, recorded as `span` lines of the usage ledger.

The clock every span is stamped from is `clock`; a test replaces it to make
time pass without waiting.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """The current time, timezone-aware, in UTC."""
        ...

    def monotonic(self) -> float:
        """Seconds on a clock that never goes backwards, for durations."""
        ...


class SystemClock:
    def now(self) -> datetime:
        raise NotImplementedError

    def monotonic(self) -> float:
        raise NotImplementedError


clock: Clock = SystemClock()
