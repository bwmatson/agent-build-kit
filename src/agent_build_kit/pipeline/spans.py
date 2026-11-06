"""Durations of a unit's time, recorded as `span` lines of the usage ledger.

The clock every span is stamped from is `clock`; a test replaces it to make
time pass without waiting.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from agent_build_kit import telemetry
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.usage_ledger import read_lines, record_line

SLOT = "slot"
USAGE_PAUSE = "usage_pause"
E2E_LOCK = "e2e_lock"
TEST_SLOT = "test_slot"


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

# What the resolution lane worker running this code is resolving (`base` or `comment`); empty in
# a build worker. The lane sets it in its own thread's context.
resolving: ContextVar[str] = ContextVar("resolving", default="")

# Told in the decision log with each record, and in the evidence of a failing run, so the
# records of one process (a tick) read together.
PROCESS_TICK = uuid.uuid4().hex[:8]

# The unit, change, node and round whose step is running, for what runs inside
# it (a unit-test command) and cannot be told them otherwise.
current_unit: ContextVar[tuple[str, str, str, int]] = ContextVar(
    "span_unit", default=("", "", "", 0)
)

# The restack point (`prepare`, `before_review`, `before_pr`) whose re-test is running, empty
# when none names it.
restack_point: ContextVar[str] = ContextVar("restack_point", default="")


class Span(Frozen):
    """A `span` line of the ledger: a stretch of a unit's time. `waited` names
    the bucket of a stretch spent waiting (`slot`, `usage_pause`, `e2e_lock`) and is empty
    for work; `command` names the unit-test command a stretch ran."""

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
    cause: str = ""


class Sample(Frozen):
    """A `sample` line of the ledger: how full the slots were as a running pass
    refreshed. Readers that do not know the kind skip it."""

    kind: str = "sample"
    at: str
    running: int
    in_review: int
    blocked: int
    queued: int
    free_workers: int
    limit: int
    cap: int


class AffectedRun(Frozen):
    """An `affected` line of the ledger: a fix round's selected run, or a scoped moved base's.
    `outcome` is whether the full run that confirmed a fix round's `agreed`, `disagreed`, or
    was `not_run` because the selected run failed; a moved base's is `moved`, which no full
    run confirms. `saved_seconds` is absent when the unit had no full run to compare with."""

    kind: str = "affected"
    at: str
    unit: str = ""
    change: str = ""
    node: str = ""
    round: int = 0
    selected: int
    total: int | None = None
    saved_seconds: float | None = None
    outcome: str


class RestackRecord(Frozen):
    """A `restack` line of the ledger: one decision to move a unit's branch onto its base.
    `point` is `prepare`, `before_review` or `before_pr`; `moved_from` is the commit the base
    was at when it moved, empty when it did not; the `changelog`, `documents`, `tests` and
    `code` counts are the files the move brought in, by kind; `outcome` is `clean`,
    `conflict` or `resolved`; a clean move that is re-tested has a second line, written when
    the re-test ran, with the same point and the `retest` set; `retest` is `none`, `lite`,
    `scoped` or `full`, with its
    `retest_seconds` and `retest_result` (`passed` or `failed`); `resolution_seconds` is the
    time a resolution took."""

    kind: str = "restack"
    at: str
    unit: str = ""
    change: str = ""
    point: str
    moved: bool
    moved_from: str = ""
    changelog: int = 0
    documents: int = 0
    tests: int = 0
    code: int = 0
    outcome: str = "clean"
    retest: str = "none"
    retest_seconds: float = 0.0
    retest_result: str = ""
    resolution_seconds: float = 0.0
    # What the resolution lane was resolving when the line was written (`base` or `comment`);
    # empty for a restack a build worker made.
    resolving: str = ""


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
    cause: str = "",
) -> None:
    """Record the time since `mark` as a span, never raising: a record that cannot
    be kept is told once through `say`."""
    try:
        ended = clock.now()
        span = Span(
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
            cause=cause,
        )
        record_line(span, say)
        export_span(span)
    except Exception as error:  # noqa: BLE001 — a span is never a run's to lose
        say(f"the usage ledger is not recording spans ({error})")


def record_sample(sample: Sample, say: Callable[[str], None]) -> None:
    """Record a sample, never raising."""
    record_line(sample, say)


def record_affected(run: AffectedRun, say: Callable[[str], None]) -> None:
    """Record a selected run, never raising."""
    record_line(run, say)


def record_restack(record: RestackRecord, say: Callable[[str], None]) -> None:
    """Record a restack decision, never raising."""
    record_line(record, say)


def read_restacks(path: Path, since: datetime | None = None) -> list[RestackRecord]:
    """The ledger's `restack` lines from `since` on; none from a ledger without any. A line
    that does not parse is skipped, as the ledger's other readers do."""
    found = []
    for line in read_lines(path):
        try:
            data = json.loads(line)
            if not isinstance(data, dict) or data.get("kind") != "restack":
                continue
            record = RestackRecord.model_validate(data)
            at = datetime.fromisoformat(record.at)
        except ValueError:
            continue
        if since is not None and (at if at.tzinfo else at.replace(tzinfo=UTC)) < since:
            continue
        found.append(record)
    return found


def export_span(span: Span) -> None:
    """Add a span's time to the metrics: a wait under its bucket, work under its
    node. A unit-test command's span is inside its node's, so it adds nothing."""
    seconds = span.duration_ms / 1000
    if span.waited:
        telemetry.duration("abk.wait.duration", seconds, bucket=span.waited)
    elif not span.command:
        telemetry.duration("abk.node.duration", seconds, node=span.node)
