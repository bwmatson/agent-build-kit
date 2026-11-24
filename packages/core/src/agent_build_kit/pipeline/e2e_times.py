"""The time of each e2e test, once the toolchain has read it: the split a test suite
printed merged onto the entries, and the ledger row and metrics each entry becomes.

A test suite reports where a phase's time went on a line of the fixed prefix `ABK-TIME`
and JSON, which any toolchain's tests can print; nothing here knows what runs the tests.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from pydantic import model_serializer

from agent_build_kit import telemetry
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.e2e import TestTime
from agent_build_kit.pipeline.usage_ledger import record_line

logger = logging.getLogger(__name__)

SPLIT_PREFIX = "ABK-TIME "


class TestTimeRow(Frozen):
    """A `test_time` line of the ledger: one phase of one test. A split figure the run did
    not give is left out of the line; readers that do not know the kind skip it."""

    __test__ = False

    kind: str = "test_time"
    at: str
    unit: str
    change: str
    marker: str
    test: str
    phase: str
    duration_ms: int
    agent_ms: int | None = None
    checks_ms: int | None = None
    other_ms: int | None = None

    @model_serializer(mode="wrap")
    def _without_absent(self, handler: Callable[[Any], dict[str, Any]]) -> dict[str, Any]:
        return {name: value for name, value in handler(self).items() if value is not None}


def with_split(entries: list[TestTime], output: str) -> list[TestTime]:
    """`entries` with the split of each `ABK-TIME` line in `output` merged onto the entry of
    its test and phase. A line that is not JSON of the right shape is ignored."""
    splits: dict[tuple[str, str], dict[str, Any]] = {}
    for line in output.splitlines():
        if not line.startswith(SPLIT_PREFIX):
            continue
        try:
            found = json.loads(line[len(SPLIT_PREFIX) :])
            splits[(str(found["test"]), str(found["phase"]))] = {
                "agent_ms": {str(k): int(v) for k, v in found.get("agent", {}).items()},
                "calls": {str(k): int(v) for k, v in found.get("calls", {}).items()},
                "checks_ms": int(found["checks_ms"]) if "checks_ms" in found else None,
                "other_ms": int(found["other_ms"]) if "other_ms" in found else None,
                "overlap": bool(found.get("overlap", False)),
            }
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    return [e.model_copy(update=splits.get((e.test, e.phase), {})) for e in entries]


def record_test_times(entries: list[TestTime], *, unit: str, change: str, marker: str) -> None:
    """Write a `test_time` row for each entry and export its time as metrics, never
    raising: a record that cannot be kept never fails a run."""
    for entry in entries:
        try:
            _record(entry, unit=unit, change=change, marker=marker)
        except Exception as error:  # noqa: BLE001 — a record is never a run's to lose
            logger.warning("e2e test time not recorded: %s", error)


def _record(entry: TestTime, *, unit: str, change: str, marker: str) -> None:
    record_line(
        TestTimeRow(
            at=spans.clock.now().isoformat(),
            unit=unit,
            change=change,
            marker=marker,
            test=entry.test,
            phase=entry.phase,
            duration_ms=round(entry.seconds * 1000),
            agent_ms=sum(entry.agent_ms.values()) if entry.has_split else None,
            checks_ms=entry.checks_ms,
            other_ms=entry.other_ms,
        ),
        logger.warning,
    )
    # The file, never the test: bounded by the number of test files.
    where = {"marker": marker, "file": entry.test.partition("::")[0]}
    telemetry.duration("abk.e2e.test.duration", entry.seconds, **where, phase=entry.phase)
    for role, ms in entry.agent_ms.items():
        telemetry.duration("abk.e2e.test.time", ms / 1000, **where, cause="agent", role=role)
    for cause, ms in (("checks", entry.checks_ms), ("other", entry.other_ms)):
        if ms is not None:
            telemetry.duration("abk.e2e.test.time", ms / 1000, **where, cause=cause, role="")
