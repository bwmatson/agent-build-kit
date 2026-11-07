"""Checks the machine was suspended in twice hold the unit for a person (spec:
suspended-check-run): no fix agent runs, no fix round is counted and no feedback is saved. The
runner hands the graph the note `SUSPENDED_NOTE` as the run's output.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.command_limit import SUSPENDED_NOTE
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import HELD
from tests.factories import unit
from tests.graph.test_build_path import FAILING, build
from tests.graph.test_remaining_paths import fresh


def test_checks_the_machine_was_suspended_in_twice_hold_the_unit_and_run_no_fix_agent(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path, unit_test_ok=False)
    recorder.unit_test_output = SUSPENDED_NOTE

    outcome = build(tmp_path, recorder)

    assert outcome.status == RunStatus.HELD
    stored = recorder.store.get(unit().id)
    assert (stored.state, stored.cause) == (HELD, Cause.NEEDS_HUMAN)
    assert "suspended" in stored.note and "abk requeue" in stored.note
    assert stored.feedback == "", "nothing is saved for a fix agent"
    assert "claude:fix_checks" not in recorder.events


def test_a_suspend_after_a_fix_round_clears_the_failure_that_round_answered(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    recorder.unit_test_results = [(False, FAILING), (False, SUSPENDED_NOTE)]

    outcome = build(tmp_path, recorder)

    assert outcome.status == RunStatus.HELD
    assert recorder.events.count("claude:fix_checks") == 1
    assert recorder.store.get(unit().id).feedback == "", "a requeue must not rework it"
