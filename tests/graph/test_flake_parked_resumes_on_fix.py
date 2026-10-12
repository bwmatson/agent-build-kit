"""A unit parked for a flaky test resumes once the fix's unit is in review, restacked onto
the fix's branch (spec: flaky-tests), not once the fix has merged."""

from __future__ import annotations

from typing import Any

from agent_build_kit.pipeline.flakes import wait_on_fix
from agent_build_kit.pipeline.unit_store import Cause, RequeueReason
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, PLANNED
from tests.factories import new_unit
from tests.graph.test_flake_parking import FLAKE, Flaking
from tests.pipeline.test_flake_fix_change import TASKS, code_repo
from tests.tick_driver import UNIT, Setup


def test_the_parked_unit_stays_gated_while_the_fix_is_held_then_restacks_onto_its_branch(
    graph: Setup,
) -> None:
    code_repo(graph.inst)
    tasks = graph.inst.changes_dir / "add-marker" / "tasks.md"
    tasks.parent.mkdir(parents=True)
    tasks.write_text(TASKS)
    tier1 = Flaking(graph.recorder, nth=1)
    bases: list[str] = []
    graph.options["run_tier1"] = tier1
    graph.options["restack_onto"] = lambda **kw: bases.append(str(kw["base"]))
    graph.options["on_flake"] = lambda unit, flake: wait_on_fix(
        graph.inst, FLAKE, graph.store.get(unit.id)
    )

    assert graph.tick() == 0

    parked = graph.store.get(UNIT)
    assert (parked.state, parked.cause) == (PLANNED, Cause.GATED)
    assert parked.gated_requeue is RequeueReason.RESUME
    (fix,) = [p.name for p in graph.inst.changes_dir.iterdir() if p.name != "add-marker"]
    graph.store.upsert([new_unit(f"{fix}/1")])
    graph.store.set_state(f"{fix}/1", HELD, branch=f"spec/{fix}/1")

    assert graph.tick() == 0
    still: Any = graph.store.get(UNIT)
    assert (still.state, still.cause) == (PLANNED, Cause.GATED)
    assert bases == []

    graph.store.set_state(f"{fix}/1", IN_REVIEW, branch=f"spec/{fix}/1", pr=9)
    assert graph.tick() == 0

    assert graph.store.get(UNIT).state == IN_REVIEW
    assert any(base.endswith(f"spec/{fix}/1") for base in bases)
