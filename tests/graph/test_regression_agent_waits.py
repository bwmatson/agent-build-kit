"""A flake, a failure on the base and a pre-existing e2e failure each start the regression agent
once and park the unit on the change it writes (spec: regression-agent).

The agent is a stand-in runtime that writes the change into the change directory; the change
a template used to write has a different tasks.md, so the agent's own is what shows it ran.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import (
    FailedOnBase,
    FlakeFound,
    flake_record,
    next_fix_name,
)
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import Cause, RequeueReason
from agent_build_kit.pipeline.units import PLANNED
from agent_build_kit.pipeline.untouched_failures import preexisting_record
from agent_build_kit.pipeline.wiring import build_on_flake, build_on_preexisting
from agent_build_kit.pipeline.work_graph import group_needs
from tests.e2e_gate_fakes import Planning
from tests.e2e_wait_fakes import OLD, verdict_of
from tests.graph.test_failed_on_base_callers import FAILING, raising
from tests.graph.test_open_fix_waited_on import failing
from tests.graph_driver import tick
from tests.pipeline.test_flake_fix_change import TEST, waits_on
from tests.regression_agent_fakes import Attempts, openspec_checking

AGENT_TASK = "Read the label at render time."


def agent_for(inst: Installation, test: str) -> Attempts:
    return Attempts(inst, next_fix_name(inst, test), {})


def test_a_failure_on_the_base_starts_the_agent_once_and_parks_the_unit_on_its_change(
    tmp_path: Path,
) -> None:
    installation, recorder = failing(tmp_path)
    agent = agent_for(installation, TEST)
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
    assert stored.gated_requeue is RequeueReason.RESUME
    assert len(agent.runtime.requests) == 1
    assert agent.runtime.request.role == "regression"
    assert AGENT_TASK in (installation.changes_dir / agent.name / "tasks.md").read_text()
    assert waits_on(installation, "add-marker") == [agent.name]


def test_a_flake_starts_the_agent_once_and_the_unit_waits_on_its_change(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    installation = planning.installation
    agent = agent_for(installation, TEST)
    on_flake = build_on_flake(
        planning.store,
        installation,
        runtime=agent.runtime,
        run_openspec=openspec_checking(installation),
        log=lambda message: None,
    )
    unit = planning.recorder.store.get("add-marker/1")
    found = FlakeFound((FAILING,))

    fix = on_flake(unit, found.flakes[0])

    assert fix == agent.name
    assert len(agent.runtime.requests) == 1
    assert "flaky" in agent.runtime.request.prompt
    assert [n.change for n in group_needs(installation.changes_dir / "add-marker/tasks.md")[1]] == [
        agent.name
    ]
    assert [row.change for row in flake_record(installation).entries()] == [agent.name]


def test_a_pre_existing_e2e_failure_starts_the_agent_once_and_the_unit_waits(
    tmp_path: Path,
) -> None:
    planning = Planning(tmp_path)
    installation = planning.installation
    agent = agent_for(installation, OLD)
    on_preexisting = build_on_preexisting(
        planning.store,
        installation,
        runtime=agent.runtime,
        run_openspec=openspec_checking(installation),
        log=lambda message: None,
    )
    verdict = verdict_of(old=(OLD,))

    fix = on_preexisting(
        planning.store.get("add-marker/1"), verdict, verdict.pre_existing[0], wait=True
    )

    assert fix == agent.name
    assert len(agent.runtime.requests) == 1
    assert "pre-existing" in agent.runtime.request.prompt
    assert [row.change for row in preexisting_record(installation).entries()] == [agent.name]
    needs = group_needs(installation.changes_dir / "add-marker" / "tasks.md")
    assert [n.change for n in needs[1]] == [agent.name]


def test_several_units_failing_on_one_test_cost_one_run(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    installation = planning.installation
    other = planning.store.get("add-marker/1").model_copy(update={"id": "other/1"})
    planning.write_change("other")
    planning.store.upsert([other.model_copy(update={"change": "other"})])
    agent = agent_for(installation, TEST)
    on_flake = build_on_flake(
        planning.store,
        installation,
        runtime=agent.runtime,
        run_openspec=openspec_checking(installation),
        log=lambda message: None,
    )
    failure = FailedOnBase((FAILING,)).failures[0]

    fixes = [on_flake(planning.store.get(unit), failure) for unit in ("add-marker/1", "other/1")]

    assert fixes == [agent.name, agent.name]
    assert len(agent.runtime.requests) == 1
