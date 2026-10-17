"""What the e2e-test node does with a failing run under each scope: an own test that fails
fails the unit with no base run and no record; under `full` the failure flow is as it was;
a passing own run says how many ran (spec: e2e-scope)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.config import E2eUnitScope
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import PLANNED
from tests.e2e_base_fakes import Runs, pytest_output
from tests.e2e_base_fakes import branch as plain_branch
from tests.e2e_scope_fakes import NEW, OLD, PASSED, WHOLE, Ran, branch, session
from tests.e2e_wait_fakes import Told
from tests.factories import unit
from tests.graph.test_build_path import build
from tests.graph.test_remaining_paths import fresh

OWN = "tests/live/test_new.py::test_new"
UNTOUCHED = "tests/far/test_far.py::test_far"


def drive(tmp_path: Path, repo: Path, base: str, gate, told: Told | None = None):
    recorder = fresh(tmp_path, tier="e2e-test")
    told = told or Told()
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
    assert [where for _, where in ran.calls] == [repo], "no base run was made"
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
