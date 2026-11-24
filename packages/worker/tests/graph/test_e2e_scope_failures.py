"""What the e2e-test node does with a failing run under each scope: an own test that fails
fails the unit with no base run and no record; under `full` the failure flow is as it was;
a passing own run says how many ran (spec: e2e-scope)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit.config import E2eUnitScope
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import (
    REQUEUE_BY,
    AutoRework,
    Cause,
    FeedbackSource,
    StoredUnit,
)
from agent_build_kit.pipeline.units import FAILED, PLANNED
from packages.worker.tests.graph.test_build_path import build
from packages.worker.tests.graph.test_remaining_paths import CLEAN, Moves, fresh
from tests.e2e_base_fakes import Runs, pytest_output
from tests.e2e_base_fakes import branch as plain_branch
from tests.e2e_scope_fakes import NEW, OLD, PASSED, WHOLE, Ran, branch, session
from tests.e2e_wait_fakes import OLD as FAILS_ON_BASE
from tests.e2e_wait_fakes import OWN as OWN_FAILURE
from tests.e2e_wait_fakes import Failing, Told, snapshot_of, verdict_of
from tests.factories import git, unit
from tests.graph_driver import tick
from tests.runner_fakes import Recorder
from tests.scheduled_e2e_fakes import ScheduledRun

OWN = "tests/live/test_new.py::test_new"
UNTOUCHED = "tests/far/test_far.py::test_far"


def drive(tmp_path: Path, repo: Path, base: str, gate, told: Told | None = None):
    recorder = fresh(tmp_path, tier="e2e-test")
    told = told or Told()
    # The step reads the remote's trunk: the base commit stands for it.
    git(repo, "update-ref", f"refs/remotes/origin/{base}", base)
    outcome = build(
        tmp_path,
        recorder,
        base=base,
        worktree=lambda *args, **kwargs: repo,
        run_e2e=gate.run,
        e2e_verdict=lambda: gate.verdict,
        on_preexisting=told,
    )
    return recorder, outcome, told


def test_an_own_test_that_fails_fails_the_unit_with_its_output_and_nothing_else(
    tmp_path: Path,
) -> None:
    repo, base = branch(tmp_path, {"tests/live/test_new.py": NEW}, base_files={"tests/t.py": OLD})
    ran = Ran(pytest_output(failed={OWN: "assert 1 == 2"}), code=1)
    gate = session(tmp_path, ran)

    recorder, outcome, told = drive(tmp_path, repo, base, gate)

    assert ran.commands[0][len(WHOLE) :] == [OWN], "only the unit's own test ran"
    assert outcome.status != RunStatus.HELD
    feedback = recorder.store.get(unit().id).feedback
    assert feedback.startswith("e2e-test failed:")
    assert "assert 1 == 2" in feedback
    # The first failure is reworked once, so the unit's own test ran twice, both in its tree.
    assert {where for _, where in ran.calls} == {repo}, "no base run was made"
    assert gate.verdict is None
    assert told.told == [], "nothing is recorded as pre-existing"
    assert not {"push", "pr"} & set(recorder.events)


def test_under_full_an_untouched_failing_test_that_fails_on_the_base_is_recorded_and_parks_it(
    tmp_path: Path,
) -> None:
    repo, base = plain_branch(tmp_path, {})
    output = pytest_output(failed={UNTOUCHED: "assert 1 == 2"})
    runs = Runs(repo, output, output)
    log: list[str] = []
    gate = session(tmp_path, runs, log=log, scope=E2eUnitScope.FULL)

    recorder, outcome, told = drive(tmp_path, repo, base, gate)

    assert any("runs whole" in line for line in log)
    assert runs.on_base, "the failing test was run on the base"
    assert told.told == [(unit().id, UNTOUCHED, True)]
    assert outcome.status == RunStatus.HELD
    stored = recorder.store.get(unit().id)
    assert (stored.state, stored.cause) == (PLANNED, Cause.GATED)


def test_an_own_run_whose_selected_tests_pass_reports_how_many_ran(tmp_path: Path) -> None:
    repo, base = branch(
        tmp_path,
        {"tests/live/test_new.py": NEW, "tests/live/test_two.py": NEW},
        base_files={"tests/t.py": OLD},
    )
    ran = Ran(PASSED)
    gate = session(tmp_path, ran)

    recorder, outcome, _ = drive(tmp_path, repo, base, gate)

    assert sorted(ran.commands[0][len(WHOLE) :]) == [
        "tests/live/test_new.py::test_new",
        "tests/live/test_two.py::test_new",
    ]
    assert gate.result is not None
    assert gate.result.passed == 2
    assert outcome.status == "open"
    assert "push" in recorder.events


# --- the automatic rework of a unit's own failure ------------------------------------


class Numbered(Failing):
    """E2e-test failing its first `fails` runs, each with output marked by the run's number."""

    def run(self, *, cwd: Path, base: str | None = None) -> tuple[bool, str]:
        self.snapshot = snapshot_of(OWN_FAILURE, tail=f"RUN-{self.runs + 1}-OUTPUT")
        return super().run(cwd=cwd, base=base)


def failing(recorder: Recorder, fails: int = 1) -> Numbered:
    return Numbered(recorder.events, "", verdict_of(own=(OWN_FAILURE,)), fails)


def run_e2e_unit(tmp_path: Path, recorder: Recorder, e2e: Failing, **overrides: Any):
    return tick(
        tmp_path,
        recorder,
        tier="e2e-test",
        run_e2e=e2e.run,
        e2e_verdict=e2e.judged,
        on_preexisting=Told(),
        **overrides,
    )


def given_run(recorder: Recorder, number: int) -> list[str]:
    """The prompts that carry the output of the e2e-test run `number`."""
    return [prompt for prompt in recorder.prompts if f"RUN-{number}-OUTPUT" in prompt]


def pipeline_reworks(stored: StoredUnit) -> list[dict]:
    """The history entries of a rework the pipeline asked for."""
    return [
        entry
        for entry in stored.history
        if entry.get("cause") == Cause.REWORK and "pipeline" in str(entry.get("note", ""))
    ]


def reworked_own_failure(root: Path) -> bool:
    """Whether an `[e2e-test]` unit of its own failure, run under `root`, is reworked once."""
    root.mkdir()
    recorder = fresh(root, tier="e2e-test")
    run_e2e_unit(root, recorder, failing(recorder))
    return recorder.store.get(unit().id).auto_reworks == (AutoRework.E2E_FAILED,)


def test_an_own_e2e_failure_is_reworked_once_with_its_output_and_the_unit_goes_on(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path, tier="e2e-test")
    e2e = failing(recorder)

    outcome = run_e2e_unit(tmp_path, recorder, e2e)

    assert outcome.status == "open"
    assert len(given_run(recorder, 1)) == 1, "the rework was given the saved e2e-test failure"
    assert recorder.events.count("e2e-test") == 2
    assert recorder.events.count("unit-test") == 2, "the checks ran again after the rework"
    assert recorder.events.count("review") == 2, "and the review"
    assert "push" in recorder.events
    stored = recorder.store.get(unit().id)
    assert stored.auto_reworks == (AutoRework.E2E_FAILED,)
    (entry,) = pipeline_reworks(stored)
    assert "e2e-test" in entry["note"]


def test_a_second_e2e_failure_fails_the_unit_with_the_second_runs_output(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path, tier="e2e-test")
    e2e = failing(recorder, fails=2)

    outcome = run_e2e_unit(tmp_path, recorder, e2e)

    assert outcome.status == "failed"
    assert "e2e-test failed" in outcome.detail
    assert len(given_run(recorder, 1)) == 1, "reworked once"
    assert given_run(recorder, 2) == [], "and not for the second failure"
    assert e2e.runs == 2
    stored = recorder.store.get(unit().id)
    assert stored.feedback_source is FeedbackSource.E2E
    assert "RUN-2-OUTPUT" in stored.feedback
    assert "RUN-1-OUTPUT" not in stored.feedback
    assert "push" not in recorder.events


def test_a_unit_requeued_after_its_automatic_rework_fails_again_with_no_rework(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path, tier="e2e-test")
    e2e = failing(recorder, fails=3)
    run_e2e_unit(tmp_path, recorder, e2e)
    prompts = len(recorder.prompts)
    recorder.store.set_feedback(unit().id, "")
    recorder.store.set_state(unit().id, PLANNED, cause=Cause.REQUEUED, by=REQUEUE_BY)

    outcome = run_e2e_unit(tmp_path, recorder, e2e)

    assert outcome.status == "failed"
    assert e2e.runs == 3, "the e2e-test ran once more"
    assert given_run(recorder, 3) == [] and len(recorder.prompts) == prompts, "no agent was run"
    stored = recorder.store.get(unit().id)
    assert stored.state == FAILED
    assert stored.auto_reworks == (AutoRework.E2E_FAILED,)
    assert len(pipeline_reworks(stored)) == 1


def test_a_rework_that_commits_nothing_stops_the_unit_without_a_second_e2e_run(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path, tier="e2e-test")
    e2e = failing(recorder)

    def commit(message: str, *, cwd: Path, base: str = "") -> int:
        if message.startswith("fix"):
            return 0
        return recorder.commit(message, cwd=cwd, base=base)

    outcome = run_e2e_unit(tmp_path, recorder, e2e, commit=commit)

    assert outcome.status == "failed"
    assert len(given_run(recorder, 1)) == 1, "the rework was asked for"
    assert e2e.runs == 1, "the stack was not brought up on an unchanged branch"
    assert "RUN-1-OUTPUT" in recorder.store.get(unit().id).feedback
    assert "push" not in recorder.events


def test_a_failure_only_of_tests_failing_on_the_base_parks_the_unit_with_no_rework(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path, tier="e2e-test")
    e2e = Failing(
        recorder.events, snapshot_of(FAILS_ON_BASE), verdict_of(old=(FAILS_ON_BASE,)), fails=1
    )

    outcome = run_e2e_unit(tmp_path, recorder, e2e)

    assert outcome.status == RunStatus.HELD
    stored = recorder.store.get(unit().id)
    assert (stored.state, stored.cause) == (PLANNED, Cause.GATED)
    assert stored.auto_reworks == ()
    assert pipeline_reworks(stored) == []
    assert e2e.runs == 1
    assert reworked_own_failure(tmp_path / "own"), "while a failure of its own is reworked"


def test_a_failure_on_a_moved_commit_restacks_and_is_not_reworked_automatically(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path, tier="e2e-test")
    moves = Moves(recorder, CLEAN)
    verdict = verdict_of(own=(OWN_FAILURE,))
    failed_on_moved: list[bool] = []

    def run(*, cwd: Path, base: str | None = None) -> tuple[bool, str]:
        recorder.events.append("e2e-test")
        # Only the run on the moved commit fails, and only once: the restack's own rerun is
        # not the subject.
        failing_run = moves.moved and not failed_on_moved
        failed_on_moved.extend([True] if failing_run else [])
        return not failing_run, snapshot_of(OWN_FAILURE, tail="MOVED-RUN-OUTPUT")

    tick(
        tmp_path,
        recorder,
        tier="e2e-test",
        run_e2e=run,
        e2e_verdict=lambda: verdict,
        on_preexisting=Told(),
        **moves.overrides(),
    )

    stored = recorder.store.get(unit().id)
    assert stored.auto_reworks == ()
    assert pipeline_reworks(stored) == []
    assert reworked_own_failure(tmp_path / "own"), "while a failure of its own is reworked"


def test_a_failing_scheduled_e2e_run_is_never_reworked(tmp_path: Path) -> None:
    failed = pytest_output(failed={"tests/live/test_live.py::test_live": "assert 1 == 2"})
    (tmp_path / "scheduled").mkdir()
    run = ScheduledRun(tmp_path / "scheduled", make_ran=lambda tree: Ran(failed, code=1))

    outcome = run.tick()

    assert outcome.status == "failed"
    assert run.recorder.prompts == [], "no agent was called"
    stored = run.stored
    assert stored.auto_reworks == ()
    assert pipeline_reworks(stored) == []
    assert reworked_own_failure(tmp_path / "own"), "while a failure of its own is reworked"
