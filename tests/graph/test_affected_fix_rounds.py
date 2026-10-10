"""Which tier 1 runs ask for a selected run (spec: affected-tests-in-fix-rounds).

Tier 1 is faked at the point the runner binds it, recording the failed output each run
was given: only a check that follows a failed check and a fixer's commit is given one, and
so only that one may be selected. Every other run is asked for in full.
"""

from __future__ import annotations

from pathlib import Path

from tests.graph.test_build_path import FAILING, build
from tests.graph.test_fresh_base_builds import CLEAN, Moving
from tests.graph_driver import fresh
from tests.runner_fakes import rejecting


def test_the_first_check_and_the_check_of_a_unit_that_never_failed_are_full(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)

    outcome = build(tmp_path, recorder)

    assert outcome.status == "open"
    assert recorder.tier1_failed_outputs == [""]


def test_the_check_after_a_failed_check_and_a_fix_is_given_the_failed_output(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    recorder.tier1_results = [(False, FAILING), (True, "")]

    outcome = build(tmp_path, recorder)

    assert outcome.status == "open"
    first, second = recorder.tier1_failed_outputs
    assert first == ""
    assert FAILING in second


def test_a_failure_of_the_selected_check_is_answered_by_the_next_fix_and_a_pass_is_the_green(
    tmp_path: Path,
) -> None:
    other = "FAILED tests/test_y.py::test_other"
    recorder = fresh(tmp_path)
    recorder.tier1_results = [(False, FAILING), (False, other), (True, "")]

    outcome = build(tmp_path, recorder)

    assert outcome.status == "open"
    steps = [e for e in recorder.events if e in ("tier1", "claude:fix_checks", "review")]
    assert steps == ["tier1", "claude:fix_checks", "tier1", "claude:fix_checks", "tier1", "review"]
    outputs = recorder.tier1_failed_outputs
    assert outputs[0] == "" and FAILING in outputs[1] and other in outputs[2]


def test_a_rework_after_review_is_checked_in_full(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    recorder.verdicts = [rejecting("rename it")]

    outcome = build(tmp_path, recorder)

    assert outcome.status == "open"
    assert recorder.tier1_failed_outputs == ["", ""]


def test_the_tier1_node_of_a_unit_moved_onto_a_new_base_after_fix_rounds_is_checked_in_full(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    recorder.tier1_results = [(False, FAILING), (True, ""), (True, "")]
    moving = Moving(recorder, CLEAN)

    outcome = build(tmp_path, recorder, **moving.overrides())

    assert outcome.status == "open"
    assert recorder.events.count("moved") == 1
    first, selected, moved = recorder.tier1_failed_outputs
    assert first == "" and FAILING in selected
    assert moved == "", "the check after a move is the gate, never a selection"
