"""The run cap holds further regression-agent runs (spec: regression-agent).

`global_limits.max_regression_runs_per_hour` bounds the runs the flake and pre-existing handlers
start between them. A run the cap holds raises `RegressionRunCapped`, which is not the answer for
a unit that builds the fix itself; a run older than the hour stops counting and is forgotten.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.regression_agent import (
    RUNS_FILE,
    FixKind,
    RegressionRunCapped,
    run_room,
    wait_on_regression,
)
from agent_build_kit.pipeline.wiring import build_on_flake, build_on_preexisting
from tests.e2e_gate_fakes import Planning
from tests.e2e_wait_fakes import OLD, verdict_of
from tests.graph.test_failed_on_base_callers import FAILING
from tests.regression_agent_fakes import DefaultAgent, openspec_checking

UNIT = "add-marker/1"
SECOND = "tests/test_widget.py::test_renders_the_title"


def planning_with_cap(tmp_path: Path, cap: int) -> Planning:
    return Planning(tmp_path, global_limits=dict(max_regression_runs_per_hour=cap))


def handlers(planning: Planning, agent: DefaultAgent):
    runs = dict(
        runtime=agent.runtime,
        run_openspec=openspec_checking(planning.installation),
        log=lambda message: None,
    )
    return (
        build_on_flake(planning.store, planning.installation, **runs),
        build_on_preexisting(planning.store, planning.installation, **runs),
    )


def test_a_second_test_in_the_hour_is_held_when_the_cap_is_one(tmp_path: Path) -> None:
    planning = planning_with_cap(tmp_path, 1)
    agent = DefaultAgent()
    on_flake, _ = handlers(planning, agent)
    unit = planning.store.get(UNIT)

    on_flake(unit, FAILING)
    with pytest.raises(RegressionRunCapped) as capped:
        on_flake(unit, FAILING.model_copy(update={"test": SECOND}))

    assert len(agent.runtime.requests) == 1
    assert "max_regression_runs_per_hour" in capped.value.note


def test_the_cap_is_shared_by_the_flake_and_the_pre_existing_handlers(tmp_path: Path) -> None:
    planning = planning_with_cap(tmp_path, 1)
    agent = DefaultAgent()
    on_flake, on_preexisting = handlers(planning, agent)
    unit = planning.store.get(UNIT)
    verdict = verdict_of(old=(OLD,))

    on_flake(unit, FAILING)
    with pytest.raises(RegressionRunCapped):
        on_preexisting(unit, verdict, verdict.pre_existing[0], wait=True)

    assert len(agent.runtime.requests) == 1


def test_a_higher_cap_lets_each_distinct_test_run(tmp_path: Path) -> None:
    planning = planning_with_cap(tmp_path, 2)
    agent = DefaultAgent()
    on_flake, _ = handlers(planning, agent)
    unit = planning.store.get(UNIT)

    on_flake(unit, FAILING)
    on_flake(unit, FAILING.model_copy(update={"test": SECOND}))

    assert len(agent.runtime.requests) == 2


def test_a_test_with_an_open_fix_costs_no_run_and_is_never_capped(tmp_path: Path) -> None:
    planning = planning_with_cap(tmp_path, 1)
    agent = DefaultAgent()
    on_flake, _ = handlers(planning, agent)
    unit = planning.store.get(UNIT)

    first = on_flake(unit, FAILING)
    again = on_flake(unit, FAILING)

    assert again == first
    assert len(agent.runtime.requests) == 1


# --- the hour ---------------------------------------------------------------------------


def test_a_run_older_than_the_hour_stops_counting_and_a_run_may_start(tmp_path: Path) -> None:
    planning = planning_with_cap(tmp_path, 1)
    inst = planning.installation
    now = spans.clock.now()
    (inst.state_dir / RUNS_FILE).write_text((now - timedelta(minutes=61)).isoformat() + "\n")
    agent = DefaultAgent()

    assert run_room(inst, now)
    fix = wait_on_regression(
        inst,
        FAILING,
        planning.store.get(UNIT),
        kind=FixKind.REGRESSION,
        runtime=agent.runtime,
        run_openspec=openspec_checking(inst),
        now=now,
        say=lambda message: None,
    )

    assert fix and len(agent.runtime.requests) == 1


def test_a_run_inside_the_hour_still_counts(tmp_path: Path) -> None:
    planning = planning_with_cap(tmp_path, 1)
    inst = planning.installation
    now = spans.clock.now()
    (inst.state_dir / RUNS_FILE).write_text((now - timedelta(minutes=59)).isoformat() + "\n")

    assert not run_room(inst, now)


def test_the_runs_older_than_the_hour_are_dropped_when_a_run_is_counted(tmp_path: Path) -> None:
    planning = planning_with_cap(tmp_path, 5)
    inst = planning.installation
    now = spans.clock.now()
    old = [(now - timedelta(hours=5 + n)).isoformat() for n in range(3)]
    recent = (now - timedelta(minutes=10)).isoformat()
    (inst.state_dir / RUNS_FILE).write_text("\n".join([*old, recent]) + "\n")

    wait_on_regression(
        inst,
        FAILING,
        planning.store.get(UNIT),
        kind=FixKind.REGRESSION,
        runtime=DefaultAgent().runtime,
        run_openspec=openspec_checking(inst),
        now=now,
        say=lambda message: None,
    )

    kept = (inst.state_dir / RUNS_FILE).read_text().split()
    assert kept == [recent, now.isoformat()]
