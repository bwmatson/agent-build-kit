"""When a unit's last recorded failed unit-test run stands in for a new one (spec: test-run-reuse).

The decision reads the ledger of unit-test runs (`runs/test-runs.jsonl`) before a unit-test slot is
taken: a failed run on the same head and base, with nothing the unit waited on merged since and no
person's rework note pending, is reused instead of run again; the second reuse holds the unit.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from agent_build_kit.model import Frozen


class ReuseContext(Frozen):
    """What the unit-test call knows about the unit when it reaches the tier."""

    unit: str
    head: str
    base: str
    # Whether a person's `abk requeue --rework` with a note is pending for the unit.
    rework_note: bool = False


def run_or_reuse(
    ledger: Path,
    context: ReuseContext,
    *,
    merged_since: Callable[[datetime], bool],
    run: Callable[[], tuple[bool, str]],
    hold: Callable[[str], None],
    log: Callable[[str], None],
) -> tuple[bool, str]:
    """The unit-test result for `context`: the recorded failure when it stands in, else `run()`.

    `run` takes the unit-test slot and runs the suite; it is not called for a reused result.
    `merged_since(started)` says whether anything the unit waited on merged after the recorded run
    began. A reuse is logged ("unchanged since the failed run at <time>; not run again"), is added
    to the ledger as a `reused` row, and returns `(False, output)` naming the failed tests. The
    second reuse for the same head and base calls `hold(note)`, the note naming the tests, head and
    base, and returns the same failed result."""
    raise NotImplementedError
