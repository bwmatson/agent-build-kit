"""A unit-test run that ends at the command's time limit holds its unit for a person (spec:
unit-test-command-limit): no fix agent runs, no fix round is counted and no feedback is saved. It
holds in the checks before review, in the unit-test after a clean move and in the run that
confirms a group already built. A failure that did not reach the limit is handled as before.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import HELD
from tests.factories import unit
from tests.graph.branch_fakes import UNIT, prepared
from tests.graph.test_build_path import FAILING, build, restacked
from tests.graph.test_fresh_base_builds import Moving
from tests.graph.test_remaining_paths import fresh

OLD_BASE = "old-base-sha"
TIMED_OUT = "unit-test command timed out after 5400 seconds and was aborted\n"
PARTIAL = f"FAILED tests/test_widget.py::test_renders_the_label\n{TIMED_OUT}"


def held_for_a_person(recorder: Any, unit_id: str = UNIT) -> None:
    stored = recorder.store.get(unit_id)
    assert (stored.state, stored.cause) == (HELD, Cause.NEEDS_HUMAN)
    assert "5400" in stored.note
    assert stored.feedback == "", "nothing is saved for a fix agent"


def test_the_checks_hold_the_unit_and_run_no_fix_agent(tmp_path: Path) -> None:
    recorder = fresh(tmp_path, unit_test_ok=False)
    recorder.unit_test_output = TIMED_OUT

    outcome = build(tmp_path, recorder)

    assert outcome.status == RunStatus.HELD
    held_for_a_person(recorder, unit().id)
    assert recorder.events.count("unit-test") == 1
    assert "claude:fix_checks" not in recorder.events
    assert "review" not in recorder.events and "push" not in recorder.events


def test_a_run_that_failed_tests_and_then_reached_the_limit_is_a_timeout_too(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path, unit_test_ok=False)
    recorder.unit_test_output = PARTIAL

    outcome = build(tmp_path, recorder)

    assert outcome.status == RunStatus.HELD
    assert "claude:fix_checks" not in recorder.events


def test_a_failure_before_the_limit_is_saved_and_fixed_as_before(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    recorder.unit_test_results = [(False, FAILING), (True, "")]

    outcome = build(tmp_path, recorder)

    assert outcome.status == "open"
    assert recorder.events.count("claude:fix_checks") == 1


def test_the_unit_test_after_a_clean_move_holds_the_unit_and_does_not_restack_again(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    recorder.unit_test_results = [(True, ""), (False, TIMED_OUT)]
    moving = Moving(recorder, restacked(old_base=OLD_BASE))

    outcome = build(tmp_path, recorder, **moving.overrides())

    assert outcome.status == RunStatus.HELD
    held_for_a_person(recorder, unit().id)
    after = recorder.events[recorder.events.index("moved") :]
    assert "push" not in after and "claude:fix_checks" not in after


def test_a_group_already_built_whose_run_times_out_holds_the_unit_and_is_not_unpaired(
    tmp_path: Path,
) -> None:
    recorder, _ = prepared(tmp_path, silent_groups=(1, 2, 3))
    overrides: dict[str, Any] = recorder.overrides(tmp_path)
    overrides.update(run_unit_test=lambda **kwargs: (False, TIMED_OUT))

    outcome = build(tmp_path, recorder, **overrides)

    assert outcome.status == RunStatus.HELD
    held_for_a_person(recorder)
