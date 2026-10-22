"""Both check loops behave as they did, now through the one routine (spec: one-check-and-fix-loop).

The fakes are the stub loop's and the branch's; each test also asserts that the routine ran, so
the behaviour is the routine's and not a copy in the node.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.graph import check_loop
from agent_build_kit.graph.nodes import BuildPath
from agent_build_kit.graph.state import UnitRun
from agent_build_kit.pipeline.flakes import Flake, FlakeFound
from agent_build_kit.pipeline.stack_runner import UNIT_TEST_FAILED
from agent_build_kit.pipeline.unit_store import FeedbackSource
from tests.factories import unit
from tests.graph.stub_loop_fakes import StubLoop, stubbed_build
from tests.graph.test_build_path import build, limited
from tests.graph_driver import fresh as fresh_store
from tests.runner_fakes import Recorder, make_runner

LINT = "tests/test_x.py:1:8: F401 `os` imported but unused"
FAILING = "FAILED tests/test_y.py::test_other - assert 1 == 2"


class Routine:
    """Counts the calls that reach the real routine."""

    def __init__(self) -> None:
        self.checks = 0
        self.fixes = 0

    def assert_ran(self, *, fix: bool = False) -> None:
        assert self.checks, "the check step ran through the shared routine"
        if fix:
            assert self.fixes, "the fix step ran through the shared routine"


@pytest.fixture
def routine(monkeypatch: pytest.MonkeyPatch) -> Routine:
    seen = Routine()
    real_check, real_fix = check_loop.check_round, check_loop.fix_round

    def check_round(*args: Any, **kwargs: Any) -> Any:
        seen.checks += 1
        return real_check(*args, **kwargs)

    def fix_round(*args: Any, **kwargs: Any) -> Any:
        seen.fixes += 1
        return real_fix(*args, **kwargs)

    monkeypatch.setattr(check_loop, "check_round", check_round)
    monkeypatch.setattr(check_loop, "fix_round", fix_round)
    return seen


def stub_looping(tmp_path: Path, **options: Any) -> StubLoop:
    stubbed_build()
    return StubLoop(fresh_store(tmp_path).store, **options)


def feedback_writes(recorder: Recorder, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    saved: list[tuple[str, Any]] = []
    original = recorder.store.set_feedback

    def record(unit_id: str, feedback: str, **kwargs: Any) -> None:
        saved.append((feedback, kwargs.get("source", FeedbackSource.NONE)))
        original(unit_id, feedback, **kwargs)

    monkeypatch.setattr(recorder.store, "set_feedback", record)
    return saved


def test_a_failing_static_check_is_saved_fixed_without_a_commit_and_the_pass_commits_the_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, routine: Routine
) -> None:
    recorder = stub_looping(tmp_path, checks=[(False, LINT), (True, "")])
    saved = feedback_writes(recorder, monkeypatch)

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "open"
    assert saved[0] == (LINT, FeedbackSource.STUB_CHECKS)
    assert recorder.events[:5] == [
        "claude:tests",
        "stub-checks",
        "claude:fix_stub",
        "stub-checks",
        "commit:test",
    ]
    assert not [s for s in recorder.subjects if s.startswith("fix:")], (
        "the stub loop commits no fix"
    )
    routine.assert_ran(fix=True)


def test_a_failing_unit_test_run_is_saved_fixed_with_a_commit_and_the_pass_clears_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, routine: Routine
) -> None:
    recorder = Recorder(fresh_store(tmp_path).store)
    recorder.unit_test_results = [(False, FAILING), (True, "")]
    saved = feedback_writes(recorder, monkeypatch)

    outcome = build(tmp_path, recorder)

    assert outcome.status == "open"
    assert saved[0] == (f"{UNIT_TEST_FAILED}\n{FAILING}", FeedbackSource.UNIT_TEST)
    assert f"fix: {unit().title} (checks, round 1)" in recorder.subjects
    assert saved[-1] == ("", FeedbackSource.NONE), "a pass clears what it answered"
    routine.assert_ran(fix=True)


def test_a_pass_leaves_feedback_whose_source_is_not_the_unit_test_run(
    tmp_path: Path, routine: Routine
) -> None:
    recorder = Recorder(fresh_store(tmp_path).store)
    path = BuildPath(
        make_runner(recorder.store, recorder, tmp_path),
        unit(),
        base="main",
        graph=[],
        run_log=None,
        tracer=None,
    )
    recorder.store.set_feedback(unit().id, "REVIEW ASKED", source=FeedbackSource.REVIEW)

    update = path.checks(UnitRun(unit_id=unit().id, change="add-marker", fix_rounds=1))

    assert update["checks_ok"] is True
    assert recorder.store.get(unit().id).feedback == "REVIEW ASKED"
    routine.assert_ran()


def test_spent_static_check_rounds_stop_with_the_stub_message(
    tmp_path: Path, routine: Routine
) -> None:
    limited(max_check_rounds=2)
    recorder = stub_looping(tmp_path, checks=[(False, f"OUT-{n}") for n in range(3)])

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "failed"
    assert "static checks still failing after 2 fix round(s) on the tests" in outcome.detail
    routine.assert_ran(fix=True)


def test_spent_check_rounds_stop_with_the_checks_message(tmp_path: Path, routine: Routine) -> None:
    limited(max_check_rounds=1)
    recorder = Recorder(fresh_store(tmp_path).store, unit_test_ok=False)
    recorder.unit_test_output = FAILING

    outcome = build(tmp_path, recorder)

    assert outcome.status == "failed"
    assert "checks still failing after 1 fix round(s), before review" in outcome.detail
    routine.assert_ran(fix=True)


def test_a_stub_fix_round_that_changes_nothing_stops_the_unit(
    tmp_path: Path, routine: Routine
) -> None:
    limited(max_check_rounds=None)
    recorder = stub_looping(tmp_path, checks=[(False, LINT)], fixes_change=False)

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "failed"
    assert "static checks failing and fix round 1 changed nothing" in outcome.detail
    routine.assert_ran(fix=True)


def test_a_checks_fix_round_that_edits_and_commits_nothing_stops_the_unit(
    tmp_path: Path, routine: Routine
) -> None:
    limited(max_check_rounds=None)
    recorder = Recorder(fresh_store(tmp_path).store, commits_from_impl=0, unit_test_ok=False)
    recorder.unit_test_output = FAILING

    outcome = build(tmp_path, recorder)

    assert outcome.status == "failed"
    assert "checks failing and fix round 1 changed nothing, before review" in outcome.detail
    routine.assert_ran(fix=True)


def test_a_stub_fix_that_edits_a_file_does_not_stop_the_unit(
    tmp_path: Path, routine: Routine
) -> None:
    recorder = stub_looping(tmp_path, checks=[(False, LINT), (True, "")])

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "open"
    assert "changed nothing" not in outcome.detail
    routine.assert_ran(fix=True)


def test_a_flake_the_unit_waits_on_parks_it_and_saves_no_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, routine: Routine
) -> None:
    flake = Flake(
        test="tests/test_widget.py::test_renders",
        command="uv run pytest -q",
        output="FAILED tests/test_widget.py::test_renders\n",
        at=datetime(2026, 3, 1, 9, 30, tzinfo=UTC),
    )

    def flaking(**kwargs: Any) -> tuple[bool, str]:
        raise FlakeFound((flake,))

    recorder = Recorder(fresh_store(tmp_path).store)
    saved = feedback_writes(recorder, monkeypatch)
    path = BuildPath(
        make_runner(
            recorder.store,
            recorder,
            tmp_path,
            run_unit_test=flaking,
            on_flake=lambda unit, flake, **kw: "fix-flaky-widget",
        ),
        unit(),
        base="main",
        graph=[],
        run_log=None,
        tracer=None,
    )

    update = path.checks(UnitRun(unit_id=unit().id, change="add-marker"))

    assert update.get("checks_ok") is not True
    assert saved == [], "no failure was saved for a flake"
    routine.assert_ran()


def test_a_fix_round_already_on_the_branch_runs_no_agent_and_returns_the_round(
    tmp_path: Path, routine: Routine
) -> None:
    recorder = Recorder(fresh_store(tmp_path).store)
    path = BuildPath(
        make_runner(recorder.store, recorder, tmp_path),
        unit(),
        base="main",
        graph=[],
        run_log=None,
        tracer=None,
    )

    update = path.fix_checks(UnitRun(unit_id=unit().id, change="add-marker", head="sha-old"))

    assert update["fix_rounds"] == 1
    assert "claude:fix_checks" not in recorder.events
    assert any("fix round 1 is already on the branch" in line for line in recorder.logged)
    assert routine.fixes == 1


def test_the_stop_digest_is_the_head_and_the_tree_state(tmp_path: Path, routine: Routine) -> None:
    """A checks-loop fix round whose agent edits nothing but whose commit step changes a file
    (the fixers' turn before the commit) moves the head, and is not stopped; a stub fix round
    that changes nothing while the head is unmoved is."""
    limited(max_check_rounds=None)
    (tmp_path / "moved").mkdir()
    (tmp_path / "unmoved").mkdir()
    moved = stub_looping(tmp_path / "moved", checks=[(True, "")])
    moved.unit_test_results = [(False, FAILING), (True, "")]
    moved.tree = "tree-never-changes"

    outcome = build(tmp_path / "moved", moved, **moved.overrides(tmp_path / "moved"))

    assert outcome.status == "open"
    assert f"fix: {unit().title} (checks, round 1)" in moved.subjects, "the commit moved the head"
    assert moved.tree == "tree-never-changes", "and the agent changed no file"

    unmoved = stub_looping(tmp_path / "unmoved", checks=[(False, LINT)], fixes_change=False)

    stopped = build(tmp_path / "unmoved", unmoved, **unmoved.overrides(tmp_path / "unmoved"))

    assert stopped.status == "failed"
    assert "static checks failing and fix round 1 changed nothing" in stopped.detail
    assert routine.fixes >= 2
