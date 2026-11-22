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
from agent_build_kit.pipeline.run_log import TestRun, append_test_run
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import MERGED, history_stamp


class ReuseContext(Frozen):
    """What the unit-test call knows about the unit when it reaches the tier."""

    unit: str
    head: str
    base: str
    # Whether a person's `abk requeue --rework` with a note is pending for the unit.
    rework_note: bool = False
    # The failure the unit's last check saved for its fix agent, kept in front of a first reuse.
    feedback: str = ""


UNCHANGED_PREFIX = "unit-test failed, unchanged since the failed run at"
HELD_PREFIX = "unit-test held after an unchanged failure:"


def run_or_reuse(
    ledger: Path,
    context: ReuseContext,
    *,
    merged_since: Callable[[datetime], bool],
    run: Callable[[], tuple[bool, str]],
    log: Callable[[str], None],
) -> tuple[bool, str]:
    """The unit-test result for `context`: the recorded failure when it stands in, else `run()`.

    `run` takes the unit-test slot and runs the suite; it is not called for a reused result.
    `merged_since(started)` says whether anything the unit waited on merged after the recorded run
    began. A reuse is logged ("unchanged since the failed run at <time>; not run again"), is added
    to the ledger as a `reused` row, and returns `(False, output)` naming the failed tests. The
    second reuse for the same head and base returns a result whose output carries the hold's note
    (`held_after_reuse` reads it), naming the tests, head and base, and says how to run again; the
    graph holds the unit with it. A row of a run that ended at its time limit, one found on the
    base and one that names no failed test never stands in for a run."""
    last = _last_run(ledger, context.unit)
    if (
        last is None
        or last.outcome != "failed"
        or last.on_base
        or last.timed_out
        or not last.failed
        or last.head != context.head
        or last.base != context.base
        or context.rework_note
        or merged_since(datetime.fromisoformat(last.started))
    ):
        return run()
    log(f"unchanged since the failed run at {last.started}; not run again")
    # The reused row keeps the recorded run's start, so a later reuse asks about merges from it.
    append_test_run(
        ledger, last.model_copy(update={"seconds": 0.0, "reused": True, "failed_detail": []})
    )
    tests = ", ".join(last.failed)
    unchanged = f"{UNCHANGED_PREFIX} {last.started}: {tests}"
    if last.reused:
        note = (
            f"the unit-test run failed {tests} on head {context.head} and base {context.base} "
            "twice with nothing changed, so it is not run a third time; a requeue with a rework "
            "note, or a new commit, runs the suite again"
        )
        return False, f"{HELD_PREFIX} {note}\n{unchanged}"
    # The failure the recorded run left for the fix agent stays in front of it.
    earlier = "\n".join(
        line for line in context.feedback.splitlines() if not line.startswith(UNCHANGED_PREFIX)
    ).strip()
    return False, f"{unchanged}\n{earlier}" if earlier else unchanged


def held_after_reuse(output: str) -> str | None:
    """The note of a second reuse, when `output` is that result (a line of its own holds it); None
    for any other output. The graph holds the unit for a person with it."""
    for line in output.splitlines():
        if line.startswith(HELD_PREFIX):
            return line.removeprefix(HELD_PREFIX).strip()
    return None


def _last_run(ledger: Path, unit: str) -> TestRun | None:
    """The unit's newest row in the ledger, or None when it has none."""
    try:
        lines = ledger.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            row = TestRun.model_validate_json(line)
        except ValueError:
            continue
        if row.unit == unit:
            return row
    return None


def merged_since(store: UnitStore, unit_id: str, started: datetime) -> bool:
    """Whether a unit `unit_id` depends on or waited on merged after `started`. A store that
    cannot be read, a unit it does not know and a merge with no readable time all answer yes,
    so the unit's tests run instead of an old failure being reused."""
    try:
        unit = store.get(unit_id)
        parents = {*unit.depends_on, *unit.needs, *unit.merge_needs, *unit.waited_on}
        for parent in parents:
            stored = store.get(parent)
            if stored.state != MERGED:
                continue
            stamps = [
                history_stamp(entry) for entry in stored.history if entry.get("state") == MERGED
            ]
            if not stamps or None in stamps or max(s for s in stamps if s) > started:
                return True
    except (OSError, ValueError, KeyError, TypeError):
        return True
    return False
