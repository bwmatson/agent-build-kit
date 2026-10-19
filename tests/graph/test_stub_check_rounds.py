"""The stub check loop is bounded by `max_check_rounds`, counted apart (spec: stub-check-loop)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.graph.nodes import BuildPath
from agent_build_kit.graph.state import UnitRun
from tests.factories import unit
from tests.graph.stub_loop_fakes import StubLoop, stubbed_build
from tests.graph.test_build_path import build, limited
from tests.graph_driver import fresh as fresh_store
from tests.runner_fakes import make_runner


def failing(count: int) -> list[tuple[bool, str]]:
    """`count` failed checks, each with output of its own, as a stub that no fix repairs."""
    return [(False, f"STUB-OUTPUT-{n}") for n in range(count)]


def looping(tmp_path: Path, **options) -> StubLoop:
    stubbed_build()
    return StubLoop(fresh_store(tmp_path).store, **options)


def stopped_before_any_tests_commit(recorder: StubLoop) -> None:
    assert "commit:test" not in recorder.events
    assert "claude:impl" not in recorder.events
    assert "review" not in recorder.events


def test_rounds_that_run_out_stop_the_unit_with_the_last_output_kept(tmp_path: Path) -> None:
    limited(max_check_rounds=2)
    recorder = looping(tmp_path, checks=failing(3))

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "failed"
    assert recorder.events.count("claude:fix_stub") == 2, "the budget, no more"
    assert recorder.events.count("stub-checks") == 3
    stopped_before_any_tests_commit(recorder)
    stored = recorder.store.get("add-marker/1")
    assert "STUB-OUTPUT-2" in stored.feedback, "the last output"


def test_zero_stops_at_the_first_failure_without_a_fix(tmp_path: Path) -> None:
    limited(max_check_rounds=0)
    recorder = looping(tmp_path, checks=failing(1))

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "failed"
    assert recorder.events.count("stub-checks") == 1
    assert "claude:fix_stub" not in recorder.events
    stopped_before_any_tests_commit(recorder)
    assert "STUB-OUTPUT-0" in recorder.store.get("add-marker/1").feedback


def test_no_limit_never_stops_on_count(tmp_path: Path) -> None:
    limited(max_check_rounds=None)
    recorder = looping(tmp_path, checks=[*failing(6), (True, "")])

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "open"
    assert recorder.events.count("claude:fix_stub") == 6
    assert recorder.events.index("commit:test") > recorder.events.index("claude:fix_stub")


def test_a_fix_that_changed_nothing_stops_the_unit_and_keeps_the_output(
    tmp_path: Path,
) -> None:
    limited(max_check_rounds=None)
    recorder = looping(tmp_path, checks=failing(2), fixes_change=False)

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "failed"
    assert "changed nothing" in outcome.detail
    assert recorder.events.count("claude:fix_stub") == 1
    stopped_before_any_tests_commit(recorder)
    assert "STUB-OUTPUT-0" in recorder.store.get("add-marker/1").feedback


def test_the_rounds_are_counted_apart_from_the_builds_check_rounds(tmp_path: Path) -> None:
    """One round of the loop used, and the build's own one fix is still there to spend."""
    limited(max_check_rounds=1)
    recorder = looping(tmp_path, checks=[*failing(1), (True, "")])
    recorder.unit_test_results = [(False, "FAILED tests/test_y.py::test_other"), (True, "")]

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "open"
    assert recorder.events.count("claude:fix_stub") == 1
    assert recorder.events.count("claude:fix_checks") == 1


def test_a_pass_starts_the_next_groups_loop_from_zero_and_clears_the_saved_output(
    tmp_path: Path,
) -> None:
    """After a loop that used two fix rounds, the update that commits the tests resets the
    count and the output kept for a stop is gone."""
    recorder = looping(tmp_path, checks=[(True, "")])
    recorder.store.set_feedback("add-marker/1", "STUB-OUTPUT-1")
    runner = make_runner(recorder.store, recorder, tmp_path, **recorder.overrides(tmp_path))
    path = BuildPath(runner, unit(), base="main", graph=[], run_log=None, tracer=None)

    update = path.stub_checks(
        UnitRun(unit_id="add-marker/1", change="add-marker", stub_rounds=2, stub_loop=True)
    )

    assert update["stub_rounds"] == 0
    assert update["stub_loop"] is False
    assert recorder.store.get("add-marker/1").feedback == ""
    assert "commit:test" in recorder.events
