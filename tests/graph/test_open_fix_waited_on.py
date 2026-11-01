"""A unit whose unit-test fails on a test that an open change already fixes, of any kind, is
parked gated on that change and its agent is not asked to fix the test (spec: regression-agent).

Unit-test is faked at the point the runner binds it: it answers with the failure output of a
pytest run, as the real one does when the tests fail.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.graph.state import EventKind, ResumeEvent
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import fix_change_name, flake_record
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import Cause, RequeueReason
from agent_build_kit.pipeline.units import PLANNED
from agent_build_kit.pipeline.wiring import build_on_flake
from tests.conftest import make_installation
from tests.e2e_base_fakes import pytest_output
from tests.factories import stored_unit
from tests.graph_driver import fresh, tick
from tests.pipeline.test_flake_fix_change import TASKS, TEST, waits_on
from tests.runner_fakes import Recorder

OUTPUT = pytest_output(failed={TEST: "assert 'a' == 'b'"})
REQUEUE = ResumeEvent(kind=EventKind.REQUEUE, requeue=RequeueReason.RESUME, reason="again")


def failing(tmp_path: Path) -> tuple[Installation, Recorder]:
    """A unit of the change `add-marker` whose unit-test always fails on `TEST`."""
    installation = make_installation(tmp_path)
    recorder = fresh(tmp_path, unit_test_ok=False)
    recorder.unit_test_output = OUTPUT
    tasks = installation.changes_dir / "add-marker" / "tasks.md"
    tasks.parent.mkdir(parents=True)
    tasks.write_text(TASKS)
    recorder.store.upsert([stored_unit("add-marker/1", groups=(1,))])
    return installation, recorder


def open_fix(installation: Installation, prefix: str) -> str:
    name = fix_change_name(TEST, prefix)
    (installation.changes_dir / name).mkdir(parents=True)
    return name


@pytest.mark.parametrize("prefix", ["fix-test", "fix-flaky", "fix-failing"])
def test_a_failing_test_with_an_open_fix_parks_the_unit_gated_on_it(
    tmp_path: Path, prefix: str
) -> None:
    installation, recorder = failing(tmp_path)
    fix = open_fix(installation, prefix)

    outcome = tick(
        tmp_path, recorder, on_flake=build_on_flake(recorder.store, installation, log=print)
    )

    assert outcome.status == RunStatus.HELD
    stored = recorder.store.get("add-marker/1")
    assert (stored.state, stored.cause) == (PLANNED, Cause.GATED)
    assert stored.gated_requeue is RequeueReason.RESUME
    assert waits_on(installation, "add-marker") == [fix]
    tasks = (installation.changes_dir / "add-marker" / "tasks.md").read_text()
    assert f"— failing test {TEST}" in tasks and "flaky test" not in tasks
    assert "flaky" not in stored.note
    assert [e for e in flake_record(installation).entries() if not e.failing] == [], "no flake"
    assert stored.feedback == "", "the test is not feedback for the unit's agent to fix"
    assert "claude:fix_checks" not in recorder.events
    assert len(recorder.unit_test_failed_outputs) == 1, "the test was not run again"


def test_a_unit_that_failed_before_the_fix_existed_gets_its_line_on_a_requeue(
    tmp_path: Path,
) -> None:
    installation, recorder = failing(tmp_path)
    tick(tmp_path, recorder, on_flake=build_on_flake(recorder.store, installation, log=print))
    fix = open_fix(installation, "fix-test")

    on_flake = build_on_flake(recorder.store, installation, log=print)
    tick(tmp_path, recorder, event=REQUEUE, on_flake=on_flake)
    outcome = tick(tmp_path, recorder, on_flake=on_flake)

    assert outcome.status == RunStatus.HELD
    stored = recorder.store.get("add-marker/1")
    assert (stored.state, stored.cause) == (PLANNED, Cause.GATED)
    assert waits_on(installation, "add-marker") == [fix]
