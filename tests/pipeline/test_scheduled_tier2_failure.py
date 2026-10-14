"""A scheduled run's failing test is pre-existing by definition, because its tree is its base:
no base run is made, the test is recorded, fixed by one change and waited on, and the released
unit runs the whole marker again (spec: tier2-schedule)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from agent_build_kit.graph.state import EventKind, ResumeEvent
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import Cause, RequeueReason
from agent_build_kit.pipeline.units import PLANNED, SATISFIED
from agent_build_kit.pipeline.untouched_failures import preexisting_record
from agent_build_kit.pipeline.wiring import build_on_preexisting
from tests.pipeline.test_flake_fix_change import changes, waits_on
from tests.scheduled_tier2_fakes import CHANGE, SUMMARY, ScheduledRun, scheduled_unit
from tests.tier2_base_fakes import Runs, pytest_output
from tests.tier2_scope_fakes import WHOLE

ONE = "tests/far/test_one.py::test_one"
TWO = "tests/far/test_two.py::test_two"
GATE_CLEARED = ResumeEvent(
    kind=EventKind.REQUEUE, requeue=RequeueReason.RESUME, reason="gate cleared"
)


def fixes(run: ScheduledRun) -> list[str]:
    return sorted(c for c in changes(run.inst) if c.startswith("fix-failing"))


def failing(*tests: str, fixed_by: str = ""):
    """A runner whose whole-marker run fails `tests`, or fails with no test named when there
    are none; it passes in a tree that holds the file `fixed_by`. Every call is kept, with
    where it ran."""

    def make(tree: Path) -> Runs:
        class Whole(Runs):
            def __call__(self, command: list[str], **kwargs: object):
                failed = super().__call__(command, **kwargs)
                if fixed_by and (Path(str(kwargs["cwd"])) / fixed_by).exists():
                    return subprocess.CompletedProcess(command, 0, SUMMARY, "")
                return failed

        named = {test: "assert 1 == 2" for test in tests}
        return Whole(tree, pytest_output(failed=named) if tests else "the stack did not start\n")

    return make


def wired(run: ScheduledRun, **more: Any) -> ScheduledRun:
    run.overrides["on_preexisting"] = build_on_preexisting(run.store, run.inst, log=run.log.append)
    run.overrides.update(more)
    return run


def test_every_failed_test_of_a_tree_equal_to_its_base_is_pre_existing_with_no_base_run(
    tmp_path: Path,
) -> None:
    run = ScheduledRun(tmp_path, make_ran=failing(ONE, TWO))

    ok, _ = run.gate.run(cwd=run.worktree(scheduled_unit(), "main"), base=run.base)

    assert not ok
    assert run.gate.verdict is not None
    assert [f.test for f in run.gate.verdict.pre_existing] == [ONE, TWO]
    assert not run.gate.verdict.own and not run.gate.verdict.broken
    assert run.ran.on_base == [], "the same tree, command and stack would answer the same"
    assert run.ran.on_unit == [WHOLE]


def test_a_failing_run_is_recorded_fixed_once_per_test_and_the_unit_waits_on_the_fixes(
    tmp_path: Path,
) -> None:
    run = wired(ScheduledRun(tmp_path, make_ran=failing(ONE, TWO)))

    outcome = run.tick()

    assert outcome.status == RunStatus.HELD
    assert [e.test for e in preexisting_record(run.inst).entries()] == [ONE, TWO]
    written = fixes(run)
    assert len(written) == 2, "one fix-failing change per test"
    assert sorted(waits_on(run.inst, CHANGE)) == written, "a Needs: line on the unit's group"
    stored = run.stored
    assert (stored.state, stored.cause) == (PLANNED, Cause.GATED)
    assert stored.gated_requeue is RequeueReason.RESUME
    assert stored.feedback == ""
    assert not {"push", "pr"} & set(run.recorder.events)
    assert run.ran.on_base == []


def test_a_fix_change_already_open_is_reported_as_existing_and_not_written_twice(
    tmp_path: Path,
) -> None:
    run = wired(ScheduledRun(tmp_path, make_ran=failing(ONE)))
    run.tick()
    (first,) = fixes(run)
    before = (run.inst.changes_dir / first / "tasks.md").read_text()
    run.log.clear()

    run.tick(event=GATE_CLEARED)
    outcome = run.tick()

    assert outcome.status == RunStatus.HELD, "the same test fails again and is waited on again"
    assert fixes(run) == [first]
    assert (run.inst.changes_dir / first / "tasks.md").read_text() == before
    assert any(f"exists: {first}" in line for line in run.log)
    assert waits_on(run.inst, CHANGE) == [first]


def test_the_released_unit_resumes_at_tier_2_and_runs_the_whole_marker(tmp_path: Path) -> None:
    run = wired(ScheduledRun(tmp_path, make_ran=failing(ONE, fixed_by="fix.txt")))
    assert run.tick().status == RunStatus.HELD
    parked = len(run.ran.calls)
    run.advance("fix.txt")  # the fix change merges to the default branch

    run.tick(event=GATE_CLEARED)
    outcome = run.tick()

    assert outcome.status == RunStatus.SATISFIED, "the resumed run is on a tree that has the fix"
    assert run.ran.on_unit[parked:] == [WHOLE], "the whole marker, again, and only that"
    assert run.stored.state == SATISFIED
    assert run.recorder.prompts == []


def test_with_base_runs_off_a_failure_fails_the_unit_and_records_nothing(tmp_path: Path) -> None:
    run = wired(ScheduledRun(tmp_path, make_ran=failing(ONE), limits={"tier2_base_runs": 0}))

    outcome = run.tick()

    assert outcome.status == RunStatus.FAILED
    assert run.stored.feedback.startswith("tier 2 failed:")
    assert ONE in run.stored.feedback
    assert preexisting_record(run.inst).entries() == []
    assert fixes(run) == []
    assert waits_on(run.inst, CHANGE) == []


def test_a_failure_with_no_readable_test_fails_the_unit_and_records_nothing(
    tmp_path: Path,
) -> None:
    run = wired(ScheduledRun(tmp_path, make_ran=failing()))

    outcome = run.tick()

    assert outcome.status == RunStatus.FAILED
    assert run.stored.feedback.startswith("tier 2 failed:")
    assert preexisting_record(run.inst).entries() == []
    assert fixes(run) == []
    assert run.stored.cause is not Cause.GATED
