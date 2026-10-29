"""A unit of a fix change sets aside a failure that is not its own and fails on the base too, and
never waits on another fix; a unit of any other change still waits (spec: fix-change-needs).

Unit-test is faked at the point the runner binds it: it raises `FailedOnBase` as the real one does
for a test that fails alone on the unit's base, and answers with pytest output for a failure that
is the unit's.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import FailedOnBase, Flake, fix_change_name
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import PLANNED
from agent_build_kit.pipeline.wiring import build_on_flake
from agent_build_kit.pipeline.work_graph import group_needs
from tests.conftest import make_installation
from tests.e2e_base_fakes import pytest_output
from tests.factories import stored_unit, unit
from tests.graph_driver import fresh, tick
from tests.pipeline.test_flake_fix_change import TASKS, TEST
from tests.runner_fakes import Recorder

OTHER = "tests/test_gadget.py::test_draws_the_frame"
OWN = "tests/test_mine.py::test_my_own_behaviour"


def failure(test: str) -> Flake:
    return Flake(
        test=test,
        command="uv run pytest -n auto -q",
        output=f"FAILED {test} - assert 'a' == 'b'\n",
        at=datetime(2026, 3, 1, 9, 30, tzinfo=UTC),
    )


def on_base(*tests: str):
    """A unit-test run whose failed tests also fail on the base."""

    def run(**kwargs: Any):
        raise FailedOnBase(tuple(failure(test) for test in tests))

    return run


def fails_with(test: str):
    """A unit-test run that fails on `test`, which the unit's base passes."""
    output = pytest_output(failed={test: "assert 'a' == 'b'"})
    return lambda **kwargs: (False, output)


def open_fix(installation: Installation, test: str) -> str:
    name = fix_change_name(test, "fix-test")
    (installation.changes_dir / name).mkdir(parents=True)
    return name


def with_unit(installation: Installation, recorder: Recorder, change: str) -> Any:
    """Add the single-group unit of `change`, whose tasks the installation holds; its run."""
    tasks = installation.changes_dir / change / "tasks.md"
    tasks.parent.mkdir(parents=True, exist_ok=True)
    tasks.write_text(TASKS)
    uid = f"{change}/1"
    recorder.store.upsert([stored_unit(uid, change=change, groups=(1,))])
    return unit(uid, change=change, groups=(1,))


def needs_of(installation: Installation, change: str) -> list[str]:
    tasks = installation.changes_dir / change / "tasks.md"
    return [n.change for needs in group_needs(tasks).values() for n in needs]


def run(
    tmp_path: Path,
    recorder: Recorder,
    subject: Any,
    installation: Installation,
    log: list[str],
    answer: Any,
):
    return tick(
        tmp_path,
        recorder,
        subject=subject,
        on_flake=build_on_flake(recorder.store, installation, log=log.append),
        run_unit_test=answer,
    )


def checked(
    tmp_path: Path, change: str, *, fixes: tuple[str, ...] = ()
) -> tuple[Installation, Recorder, Any, list[str]]:
    """A unit of `change`, with an open fix change for each of `fixes`; the lines the pipeline
    logged, which start empty."""
    installation = make_installation(tmp_path)
    recorder = fresh(tmp_path, unit_test_ok=False)
    subject = with_unit(installation, recorder, change)
    for test in fixes:
        open_fix(installation, test)
    return installation, recorder, subject, []


def test_a_fix_unit_sets_aside_a_failure_another_fix_covers(tmp_path: Path) -> None:
    installation, recorder, subject, log = checked(tmp_path, "fix-test-mine", fixes=(OTHER,))

    outcome = run(tmp_path, recorder, subject, installation, log, on_base(OTHER))

    assert outcome.status != RunStatus.HELD
    stored = recorder.store.get("fix-test-mine/1")
    assert (stored.state, stored.cause) != (PLANNED, Cause.GATED)
    assert needs_of(installation, "fix-test-mine") == []
    assert "claude:fix_checks" not in recorder.events, "the failure is not the unit's to fix"
    assert any(OTHER in line and "recorded as" in line and "no wait" in line for line in log), log


def test_a_fix_unit_sets_aside_a_base_failure_no_fix_covers_yet(tmp_path: Path) -> None:
    installation, recorder, subject, log = checked(tmp_path, "fix-test-mine")

    outcome = run(tmp_path, recorder, subject, installation, log, on_base(OTHER))

    assert outcome.status != RunStatus.HELD
    written = installation.changes_dir / fix_change_name(OTHER, "fix-test")
    assert written.is_dir(), "the fix change is still written"
    assert needs_of(installation, "fix-test-mine") == []
    assert "claude:fix_checks" not in recorder.events
    assert any(OTHER in line and "no wait" in line for line in log), log


def test_a_fix_unit_still_fails_for_a_test_that_passes_on_the_base(tmp_path: Path) -> None:
    installation, recorder, subject, log = checked(tmp_path, "fix-test-mine", fixes=(OTHER,))

    run(tmp_path, recorder, subject, installation, log, fails_with(OTHER))

    assert "claude:fix_checks" in recorder.events, "the unit's agent is asked to fix it"
    assert needs_of(installation, "fix-test-mine") == []
    assert recorder.store.get("fix-test-mine/1").cause is not Cause.GATED


def test_a_fix_unit_still_fails_for_its_own_test(tmp_path: Path) -> None:
    installation, recorder, subject, log = checked(tmp_path, "fix-test-mine")

    run(tmp_path, recorder, subject, installation, log, fails_with(OWN))

    assert "claude:fix_checks" in recorder.events
    assert needs_of(installation, "fix-test-mine") == []


def test_a_feature_unit_still_waits_on_the_fix(tmp_path: Path) -> None:
    installation, recorder, subject, log = checked(tmp_path, "add-marker", fixes=(OTHER,))

    outcome = run(tmp_path, recorder, subject, installation, log, on_base(OTHER))

    assert outcome.status == RunStatus.HELD
    stored = recorder.store.get("add-marker/1")
    assert (stored.state, stored.cause) == (PLANNED, Cause.GATED)
    assert needs_of(installation, "add-marker") == [fix_change_name(OTHER, "fix-test")]


def test_two_fix_units_for_different_tests_both_complete_their_checks(tmp_path: Path) -> None:
    installation = make_installation(tmp_path)
    recorder = fresh(tmp_path, unit_test_ok=False)
    first_change = open_fix(installation, TEST)
    second_change = open_fix(installation, OTHER)
    first = with_unit(installation, recorder, first_change)
    second = with_unit(installation, recorder, second_change)
    log: list[str] = []

    one = run(tmp_path, recorder, first, installation, log, on_base(OTHER))
    two = run(tmp_path, recorder, second, installation, log, on_base(TEST))

    assert one.status != RunStatus.HELD and two.status != RunStatus.HELD
    assert needs_of(installation, first_change) == []
    assert needs_of(installation, second_change) == []
    for uid in (f"{first_change}/1", f"{second_change}/1"):
        assert recorder.store.get(uid).cause is not Cause.GATED
