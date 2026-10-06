"""Durations of a unit's time, recorded as `span` lines of the usage ledger.

The clock every span is stamped from is `clock`; a test replaces it to make
time pass without waiting.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Protocol

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.usage_ledger import record_line

SLOT = "slot"
USAGE_PAUSE = "usage_pause"


class Clock(Protocol):
    def now(self) -> datetime:
        """The current time, timezone-aware, in UTC."""
        ...

    def monotonic(self) -> float:
        """Seconds on a clock that never goes backwards, for durations."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()


clock: Clock = SystemClock()

# The unit, change, node and round whose step is running, for what runs inside
# it (a tier 1 command) and cannot be told them otherwise.
current_unit: ContextVar[tuple[str, str, str, int]] = ContextVar(
    "span_unit", default=("", "", "", 0)
)


class Span(Frozen):
    """A `span` line of the ledger: a stretch of a unit's time. `waited` names
    the bucket of a stretch spent waiting (`slot`, `usage_pause`) and is empty
    for work; `command` names the tier 1 command a stretch ran."""

    kind: str = "span"
    at: str
    unit: str = ""
    change: str = ""
    node: str = ""
    round: int = 0
    started: str
    ended: str
    duration_ms: int
    outcome: str = "ok"
    waited: str = ""
    command: str = ""


class Mark:
    """A moment on `clock`, to measure a span from."""

    def __init__(self, at: datetime | None = None) -> None:
        now = clock.now()
        self.at = at or now
        self.tick = clock.monotonic() - (now - self.at).total_seconds()


def record_span(
    mark: Mark,
    say: Callable[[str], None],
    *,
    unit: str = "",
    change: str = "",
    node: str = "",
    round_number: int = 0,
    outcome: str = "ok",
    waited: str = "",
    command: str = "",
) -> None:
    """Record the time since `mark` as a span, never raising: a record that cannot
    be kept is told once through `say`."""
    try:
        ended = clock.now()
        record_line(
            Span(
                at=ended.isoformat(),
                unit=unit,
                change=change,
                node=node,
                round=round_number,
                started=mark.at.isoformat(),
                ended=ended.isoformat(),
                duration_ms=max(0, round((clock.monotonic() - mark.tick) * 1000)),
                outcome=outcome,
                waited=waited,
                command=command,
            ),
            say,
        )
    except Exception as error:  # noqa: BLE001 — a span is never a run's to lose
        say(f"the usage ledger is not recording spans ({error})")
