"""A unit whose failure the hour's cap on agent runs holds is held and not failed, and the run
starts on a later tick once the hour has room (spec: regression-agent).

Unit-test is faked at the point the runner binds it, and the agent is a stand-in runtime.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from agent_build_kit.cli.pipeline import release_gated
from agent_build_kit.graph.state import EventKind, ResumeEvent
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.regression_agent import CAPPED_NOTE, RUNS_FILE
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import Cause, RequeueReason, UnitStore
from agent_build_kit.pipeline.units import PLANNED
from agent_build_kit.pipeline.wiring import build_on_flake
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.graph.test_failed_on_base_callers import (
    change_with_unit,
    code_repo,
    raising,
    restack_of,
)
from tests.graph.test_open_fix_waited_on import TASKS
from tests.graph_driver import fresh, tick
from tests.pipeline.test_flake_fix_change import waits_on
from tests.regression_agent_fakes import DefaultAgent
from tests.regression_agent_support import openspec_checking
from tests.runner_fakes import Recorder

REQUEUE = ResumeEvent(kind=EventKind.REQUEUE, requeue=RequeueReason.RESUME, reason="again")


def started(installation: Installation, *, minutes_ago: int) -> None:
    """One run of the agent, started `minutes_ago` minutes ago."""
    at = spans.clock.now() - timedelta(minutes=minutes_ago)
    (installation.state_dir / RUNS_FILE).parent.mkdir(parents=True, exist_ok=True)
    (installation.state_dir / RUNS_FILE).write_text(at.isoformat() + "\n")


def capped(tmp_path: Path) -> tuple[Installation, Recorder, DefaultAgent]:
    """A unit of `add-marker` whose unit-test fails on `TEST` on its base too, with one run of
    the agent already started this hour and a cap of one."""
    installation = make_installation(tmp_path, global_limits=dict(max_regression_runs_per_hour=1))
    recorder = fresh(tmp_path, unit_test_ok=False)
    tasks = installation.changes_dir / "add-marker" / "tasks.md"
    tasks.parent.mkdir(parents=True)
    tasks.write_text(TASKS)
    recorder.store.upsert([stored_unit("add-marker/1", groups=(1,))])
    started(installation, minutes_ago=5)
    return installation, recorder, DefaultAgent()


def test_a_unit_whose_failure_the_cap_holds_is_held_and_not_failed(tmp_path: Path) -> None:
    installation, recorder, agent = capped(tmp_path)
    on_flake = build_on_flake(
        recorder.store,
        installation,
        runtime=agent.runtime,
        run_openspec=openspec_checking(installation),
        log=print,
    )

    outcome = tick(tmp_path, recorder, run_unit_test=raising, on_flake=on_flake)

    assert outcome.status == RunStatus.HELD
    stored = recorder.store.get("add-marker/1")
    assert (stored.state, stored.cause) == (PLANNED, Cause.GATED)
    assert stored.note.startswith(CAPPED_NOTE) and "max_regression_runs_per_hour" in stored.note
    assert stored.gated_requeue is RequeueReason.RESUME
    assert stored.feedback == "", "the test is not the unit's to fix"
    assert agent.runtime.requests == []
    assert waits_on(installation, "add-marker") == []


def test_a_capped_unit_is_not_released_while_the_hour_is_full(tmp_path: Path) -> None:
    installation, recorder, agent = capped(tmp_path)
    on_flake = build_on_flake(recorder.store, installation, runtime=agent.runtime, log=print)
    tick(tmp_path, recorder, run_unit_test=raising, on_flake=on_flake)

    release_gated(installation, recorder.store)

    stored = recorder.store.get("add-marker/1")
    assert stored.gated_requeue is RequeueReason.RESUME, "its requeue was not delivered"
    assert stored.note.startswith(CAPPED_NOTE)


def test_the_run_starts_on_a_later_tick_once_the_hour_has_room(tmp_path: Path) -> None:
    installation, recorder, agent = capped(tmp_path)
    on_flake = build_on_flake(
        recorder.store,
        installation,
        runtime=agent.runtime,
        run_openspec=openspec_checking(installation),
        log=print,
    )
    tick(tmp_path, recorder, run_unit_test=raising, on_flake=on_flake)
    started(installation, minutes_ago=90)

    tick(tmp_path, recorder, event=REQUEUE, run_unit_test=raising, on_flake=on_flake)
    tick(tmp_path, recorder, run_unit_test=raising, on_flake=on_flake)

    assert len(agent.runtime.requests) == 1
    stored = recorder.store.get("add-marker/1")
    assert (stored.state, stored.cause) == (PLANNED, Cause.GATED)
    assert not stored.note.startswith(CAPPED_NOTE)
    assert len(waits_on(installation, "add-marker")) == 1


def test_a_restacked_unit_whose_failure_the_cap_holds_waits_planned_and_gated(
    tmp_path: Path,
) -> None:
    installation = make_installation(tmp_path, global_limits=dict(max_regression_runs_per_hour=1))
    code_repo(installation)
    child = change_with_unit(installation, "feature", "feature/1").model_copy(
        update={"pr": 2, "branch": "spec/feature/1", "approved": "approved"}
    )
    store = UnitStore(installation.root / "units.json")
    store.upsert([child])
    started(installation, minutes_ago=5)

    pushed = restack_of(store, installation, child)

    stored = store.get("feature/1")
    assert (stored.state, stored.cause) == (PLANNED, Cause.GATED)
    assert stored.note.startswith(CAPPED_NOTE)
    assert pushed == []
