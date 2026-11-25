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
from agent_build_kit.pipeline.stack_runner import UNIT_TEST_FAILED, Recheck, RunStatus
from agent_build_kit.pipeline.unit_store import Cause, FeedbackSource, HeldBy
from agent_build_kit.pipeline.units import FAILED, HELD, PLANNED
from agent_build_kit.pipeline.wiring import build_unit_test_recheck
from packages.worker.tests.graph.test_build_path import build, limited
from tests.e2e_base_fakes import pytest_output
from tests.factories import stored_unit, unit
from tests.failure_bundle_fakes import BundleProfile, RerunMachine
from tests.graph.stub_loop_fakes import StubLoop, feedback_writes, stubbed_build
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


def test_a_checks_fix_round_that_edits_and_commits_nothing_stops_a_runner_that_cannot_recheck(
    tmp_path: Path, routine: Routine
) -> None:
    limited(max_check_rounds=None)
    recorder = Recorder(fresh_store(tmp_path).store, commits_from_impl=0, unit_test_ok=False)
    recorder.unit_test_output = FAILING

    outcome = build(tmp_path, recorder, recheck_unit_test=lambda **_: None)

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


TEST_ID = "tests/test_y.py::test_other"
BUNDLES = ("bundles/first", "bundles/rerun", "bundles/recheck")


def no_change_recorder(tmp_path: Path, *rechecks: Recheck) -> Recorder:
    """A recorder whose unit-test run fails once and whose fix round commits nothing."""
    limited(max_check_rounds=None)
    recorder = Recorder(fresh_store(tmp_path).store, commits_from_impl=0)
    recorder.unit_test_results = [(False, FAILING), (True, "")]
    recorder.recheck_results = list(rechecks)
    return recorder


def test_a_no_change_fix_round_that_then_passes_goes_on_to_review_after_one_recheck(
    tmp_path: Path, routine: Routine
) -> None:
    passed = Recheck(passed=True, tests=(TEST_ID,), first_output=FAILING, bundles=BUNDLES[:2])
    recorder = no_change_recorder(tmp_path, passed)

    outcome = build(tmp_path, recorder)

    assert outcome.status == "open"
    assert recorder.rechecks == [f"{UNIT_TEST_FAILED}\n{FAILING}"]
    steps = [e for e in recorder.events if e in ("unit-test", "recheck", "review")]
    assert steps == ["unit-test", "recheck", "review"], "no second run of the checks"
    assert recorder.unexplained == [passed], "the ledger holds the first run's evidence"
    assert any("after a recheck" in line for line in recorder.logged), recorder.logged
    routine.assert_ran(fix=True)


def test_a_no_change_fix_round_whose_recheck_fails_holds_the_unit_for_a_person(
    tmp_path: Path, routine: Routine
) -> None:
    failed = Recheck(
        passed=False, tests=(TEST_ID,), first_output=FAILING, output=FAILING, bundles=BUNDLES
    )
    recorder = no_change_recorder(tmp_path, failed)

    outcome = build(tmp_path, recorder)

    stored = recorder.store.get(unit().id)
    assert outcome.status == RunStatus.HELD
    assert (stored.state, stored.cause, stored.held_by) == (
        HELD,
        Cause.NEEDS_HUMAN,
        HeldBy.CHECKS,
    )
    assert stored.held_by_the_checks
    assert TEST_ID in stored.note and "three" in stored.note
    assert all(bundle in stored.note for bundle in BUNDLES)
    assert len(recorder.rechecks) == 1
    assert recorder.unexplained == []
    assert "review" not in recorder.events and "push" not in recorder.events
    routine.assert_ran(fix=True)


def test_one_recheck_is_made_for_the_no_change_round_and_none_for_the_round_that_committed(
    tmp_path: Path, routine: Routine
) -> None:
    limited(max_check_rounds=None)
    recorder = Recorder(fresh_store(tmp_path).store)
    recorder.unit_test_results = [(False, FAILING), (False, FAILING), (True, "")]
    # The build, the first fix round, then the second round's two attempts.
    recorder.commits_by_round = [1, 1, 0, 0]
    passed = Recheck(passed=True, tests=(TEST_ID,), first_output=FAILING, bundles=BUNDLES[:2])
    recorder.recheck_results = [passed]

    outcome = build(tmp_path, recorder)

    assert outcome.status == "open"
    steps = [e for e in recorder.events if e in ("unit-test", "recheck", "review")]
    assert steps == ["unit-test", "unit-test", "recheck", "review"]
    attempts = recorder.events.count("claude:fix_checks")
    assert attempts == 3, "one attempt, then two in the no-change round"
    assert len(recorder.rechecks) == 1
    routine.assert_ran(fix=True)


def fix_prompts(recorder: Recorder) -> list[str]:
    """The prompts the checks fix agent was given, in order."""
    return [p for p in recorder.prompts if "checks (lint" in p]


def test_a_fix_round_that_changes_nothing_makes_one_more_attempt_before_the_recheck(
    tmp_path: Path, routine: Routine
) -> None:
    passed = Recheck(passed=True, tests=(TEST_ID,), first_output=FAILING, bundles=BUNDLES[:2])
    recorder = no_change_recorder(tmp_path, passed)

    outcome = build(tmp_path, recorder)

    assert outcome.status == "open"
    steps = [e for e in recorder.events if e in ("claude:fix_checks", "recheck", "review")]
    assert steps == ["claude:fix_checks", "claude:fix_checks", "recheck", "review"]
    assert len(recorder.rechecks) == 1
    routine.assert_ran(fix=True)


def test_the_second_attempt_is_told_the_last_one_changed_nothing_and_given_the_lint_output(
    tmp_path: Path, routine: Routine
) -> None:
    limited(max_check_rounds=None)
    recorder = Recorder(fresh_store(tmp_path).store, commits_from_impl=0, unit_test_ok=False)
    recorder.unit_test_output = LINT

    build(tmp_path, recorder, recheck_unit_test=lambda **_: None)

    prompts = fix_prompts(recorder)
    assert len(prompts) == 2, "a second attempt was made"
    first, second = prompts
    assert "changed nothing" not in first
    assert "changed nothing" in second
    assert LINT in second
    routine.assert_ran(fix=True)


def test_a_second_attempt_that_commits_runs_the_checks_again_with_no_recheck_and_one_round(
    tmp_path: Path, routine: Routine
) -> None:
    limited(max_check_rounds=None)
    recorder = Recorder(fresh_store(tmp_path).store)
    recorder.unit_test_results = [(False, FAILING), (True, "")]
    recorder.commits_by_round = [1, 0, 1]  # the build, then the first and the second attempt

    outcome = build(tmp_path, recorder)

    assert outcome.status == "open"
    steps = [e for e in recorder.events if e in ("unit-test", "claude:fix_checks", "recheck")]
    assert steps == ["unit-test", "claude:fix_checks", "claude:fix_checks", "unit-test"]
    assert recorder.rechecks == []
    assert not any("round 2" in subject for subject in recorder.subjects), "one round was counted"
    routine.assert_ran(fix=True)


def test_two_attempts_that_change_nothing_stop_a_runner_that_cannot_recheck(
    tmp_path: Path, routine: Routine
) -> None:
    limited(max_check_rounds=None)
    recorder = Recorder(fresh_store(tmp_path).store, commits_from_impl=0, unit_test_ok=False)
    recorder.unit_test_output = FAILING

    outcome = build(tmp_path, recorder, recheck_unit_test=lambda **_: None)

    assert outcome.status == "failed"
    assert "checks failing and fix round 1 changed nothing, before review" in outcome.detail
    assert recorder.events.count("claude:fix_checks") == 2
    routine.assert_ran(fix=True)


RED = pytest_output(failed={TEST_ID: "assert 1 == 2"})


def wired_recheck(tmp_path: Path, *, reruns: list[int]) -> tuple[RerunMachine, Any]:
    """The recheck the installation's runner is built with, over a machine whose serial runs
    exit as `reruns` says, keeping its bundles in a folder of its own."""
    machine = RerunMachine(tmp_path, reruns=reruns)
    recheck = build_unit_test_recheck(
        run=machine, profile=BundleProfile(), failures_dir=tmp_path / "bundles"
    )
    return machine, recheck


def test_a_no_change_round_whose_two_attempts_change_nothing_goes_on_when_the_wired_rerun_passes(
    tmp_path: Path, routine: Routine
) -> None:
    limited(max_check_rounds=None)
    recorder = Recorder(fresh_store(tmp_path).store, commits_from_impl=0)
    recorder.unit_test_results = [(False, RED), (True, "")]
    machine, recheck = wired_recheck(tmp_path, reruns=[0])

    outcome = build(tmp_path, recorder, recheck_unit_test=recheck)

    assert outcome.status == "open"
    assert [[a for a in c if "::" in a] for c, _ in machine.serial] == [[TEST_ID]]
    assert recorder.events.count("claude:fix_checks") == 2
    (entry,) = recorder.unexplained
    assert entry.passed and entry.tests == (TEST_ID,)
    assert RED.strip() in entry.first_output
    assert any("after a recheck" in line for line in recorder.logged), recorder.logged
    assert "review" in recorder.events
    routine.assert_ran(fix=True)


def test_a_no_change_round_whose_wired_rerun_fails_holds_the_unit_with_the_tests_named(
    tmp_path: Path, routine: Routine
) -> None:
    limited(max_check_rounds=None)
    recorder = Recorder(fresh_store(tmp_path).store, commits_from_impl=0)
    recorder.unit_test_results = [(False, RED), (True, "")]
    _, recheck = wired_recheck(tmp_path, reruns=[1])

    outcome = build(tmp_path, recorder, recheck_unit_test=recheck)

    stored = recorder.store.get(unit().id)
    assert outcome.status == RunStatus.HELD
    assert (stored.state, stored.cause) == (HELD, Cause.NEEDS_HUMAN)
    assert TEST_ID in stored.note and "three" in stored.note
    assert recorder.unexplained == []
    assert "review" not in recorder.events
    routine.assert_ran(fix=True)


OTHER_ID = "tests/test_z.py::test_third"
TWO_FAILED = f"FAILED {TEST_ID} - assert 1 == 2\nFAILED {OTHER_ID} - assert 3 == 4"
FIX_FILED = "fix-test-widget"


class OnBase:
    """A `unit_test_on_base` answering `failing` and an `on_flake` filing a change per test;
    both keep what they were given."""

    def __init__(self, *failing: str) -> None:
        self.failing = list(failing)
        self.asked: list[str] = []
        self.filed: list[str] = []

    def on_base(self, *, cwd: Path, base: str, failed_output: str) -> list[str]:
        self.asked.append(failed_output)
        return self.failing

    def on_flake(self, unit: Any, flake: Flake, *, wait: bool = True) -> str:
        self.filed.append(flake.test)
        return FIX_FILED

    def overrides(self) -> dict[str, Any]:
        return {"unit_test_on_base": self.on_base, "on_flake": self.on_flake}


def assert_parked_gated(recorder: Recorder, outcome: Any) -> None:
    stored = recorder.store.get(unit().id)
    assert outcome.status == RunStatus.HELD
    assert (stored.state, stored.cause) == (PLANNED, Cause.GATED)
    assert stored.state != FAILED


def assert_base_check_is_live(tmp_path: Path, base: OnBase) -> None:
    """The control: a plain unit whose checks fail on a named test is parked by this base check,
    so a case that expects no parking is not passing for want of the seam."""
    control = tmp_path / "control"
    control.mkdir()
    recorder = Recorder(fresh_store(control).store, unit_test_ok=False)
    recorder.unit_test_output = FAILING
    outcome = build(control, recorder, **base.overrides())
    assert_parked_gated(recorder, outcome)
    assert base.filed == [TEST_ID], "the control unit got its fix change"
    base.filed.clear()


def test_spent_fix_rounds_on_a_test_red_on_the_base_file_a_fix_and_park_the_unit_gated(
    tmp_path: Path, routine: Routine
) -> None:
    limited(max_check_rounds=1)
    recorder = Recorder(fresh_store(tmp_path).store, unit_test_ok=False)
    recorder.unit_test_output = FAILING
    base = OnBase(TEST_ID)

    outcome = build(tmp_path, recorder, **base.overrides())

    assert_parked_gated(recorder, outcome)
    assert base.filed == [TEST_ID]
    assert base.asked == [f"{UNIT_TEST_FAILED}\n{FAILING}"]
    feedback = recorder.store.get(unit().id).feedback
    assert FAILING in feedback, "the saved feedback keeps the output"
    assert feedback.count(TEST_ID) > FAILING.count(TEST_ID), "and names the test as found on base"
    routine.assert_ran(fix=True)


def test_a_no_change_round_on_a_test_red_on_the_base_parks_the_unit_with_no_second_try(
    tmp_path: Path, routine: Routine
) -> None:
    recorder = no_change_recorder(tmp_path)
    base = OnBase(TEST_ID)

    outcome = build(tmp_path, recorder, **base.overrides())

    assert_parked_gated(recorder, outcome)
    assert base.filed == [TEST_ID]
    assert recorder.events.count("claude:fix_checks") == 1, "no second attempt"
    assert recorder.rechecks == [], "and no recheck"
    assert "review" not in recorder.events
    routine.assert_ran(fix=True)


def test_only_the_test_red_on_the_base_gets_a_fix_and_is_named_when_the_other_passes_there(
    tmp_path: Path, routine: Routine
) -> None:
    limited(max_check_rounds=1)
    recorder = Recorder(fresh_store(tmp_path).store, unit_test_ok=False)
    recorder.unit_test_output = TWO_FAILED
    base = OnBase(TEST_ID)

    outcome = build(tmp_path, recorder, **base.overrides())

    assert_parked_gated(recorder, outcome)
    assert base.filed == [TEST_ID], "a fix change for the first only"
    feedback = recorder.store.get(unit().id).feedback
    assert TWO_FAILED in feedback, "the whole output is kept"
    assert feedback.count(TEST_ID) > TWO_FAILED.count(TEST_ID)
    assert feedback.count(OTHER_ID) == TWO_FAILED.count(OTHER_ID), "the other is not named"
    routine.assert_ran(fix=True)


def test_a_base_check_that_answers_none_stops_the_unit_with_the_checks_message(
    tmp_path: Path, routine: Routine
) -> None:
    limited(max_check_rounds=1)
    recorder = Recorder(fresh_store(tmp_path).store, unit_test_ok=False)
    recorder.unit_test_output = FAILING
    base = OnBase()

    outcome = build(tmp_path, recorder, **base.overrides())

    assert outcome.status == "failed"
    assert "checks still failing after 1 fix round(s), before review" in outcome.detail
    assert base.asked, "the base was asked"
    assert base.filed == [], "and no fix change was filed"
    routine.assert_ran(fix=True)


def test_a_lint_failure_naming_no_test_is_not_sent_to_the_base_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, routine: Routine
) -> None:
    limited(max_check_rounds=1)
    recorder = Recorder(fresh_store(tmp_path).store, unit_test_ok=False)
    recorder.unit_test_output = LINT
    saved = feedback_writes(recorder, monkeypatch)
    base = OnBase(TEST_ID)

    outcome = build(tmp_path, recorder, **base.overrides())

    assert outcome.status == "failed"
    assert base.asked == [], "nothing was run on the base"
    assert base.filed == []
    assert saved[0] == (f"{UNIT_TEST_FAILED}\n{LINT}", FeedbackSource.UNIT_TEST)
    assert_base_check_is_live(tmp_path, base)
    routine.assert_ran(fix=True)


def test_a_unit_of_a_fix_change_is_not_parked_on_a_test_red_on_the_base(
    tmp_path: Path, routine: Routine
) -> None:
    limited(max_check_rounds=1)
    uid = "fix-test-widget/1"
    store = fresh_store(tmp_path).store
    store.upsert([stored_unit(uid, change="fix-test-widget", groups=(1,))])
    recorder = Recorder(store, unit_test_ok=False)
    recorder.unit_test_output = FAILING
    base = OnBase(TEST_ID)

    outcome = build(tmp_path, recorder, unit_id=uid, **base.overrides())

    assert outcome.status == "failed"
    assert "checks still failing after 1 fix round(s), before review" in outcome.detail
    assert base.filed == []
    assert recorder.store.get(uid).cause is not Cause.GATED
    assert_base_check_is_live(tmp_path, base)
    routine.assert_ran(fix=True)
