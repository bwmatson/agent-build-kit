"""Admission counts a comment rework running in the resolution lane as holding a place and no build
worker, though it holds its branch lock as a build does; a moved-base run in the lane holding its
lock still takes a worker (spec: resolution-lane, one lane resolves what an open pull request
waits on)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.admission import admit, current_occupancy
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import RUNNING, project_key
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.conftest import make_installation
from tests.factories import new_unit
from tests.lane_run_slots import as_comment_run

CAP = 2
TTL = timedelta(minutes=10)


def workspace(tmp_path: Path) -> tuple[Installation, UnitStore]:
    inst = make_installation(
        tmp_path, project_limits=dict(max_concurrent_stacks=CAP, max_units_in_progress=50)
    )
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert(
        [new_unit("run1/1", branch="spec/run1/1"), *(new_unit(f"n{n}/1") for n in range(CAP))]
    )
    store.set_state("run1/1", RUNNING, branch="spec/run1/1")
    return inst, store


def candidates(store: UnitStore) -> list[str]:
    return [unit.id for unit in store.all() if unit.id.startswith("n")]


def admitted(inst: Installation, store: UnitStore) -> list[str]:
    now = datetime.now(UTC)
    return [
        unit.id
        for unit in admit(inst, store, store.all(), worker="w", now=now, ttl=TTL)
        if unit.id.startswith("n")
    ]


def test_a_comment_rework_holding_its_branch_lock_takes_no_worker_from_admission(
    tmp_path: Path,
) -> None:
    inst, store = workspace(tmp_path)
    as_comment_run(store, "run1/1")

    with branch_lock("spec/run1/1", root=inst.locks_dir):
        found = current_occupancy(inst, store.all(), datetime.now(UTC))
        assert admitted(inst, store) == candidates(store)

    key = project_key(store.get("run1/1"))
    assert found.workers.get(key, 0) == 0
    assert found.projects[key] == 1, "it still holds its place"


def test_a_moved_base_run_holding_its_branch_lock_takes_a_worker(tmp_path: Path) -> None:
    inst, store = workspace(tmp_path)
    store.set_moved_base_run("run1/1", True)

    with branch_lock("spec/run1/1", root=inst.locks_dir):
        got = admitted(inst, store)

    assert got == candidates(store)[: CAP - 1]
