"""The thread pool's round and admission agree on the same fixtures: the units the round hands out
are the units admission lets start, and the free places the pure function reports."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli.pipeline import slot_occupancy
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.admission import admit, current_occupancy, limits_of
from agent_build_kit.pipeline.occupancy import Limits, free, occupied
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, RUNNING, UnitState, project_key
from tests.branch_lock_fakes import lock_held_by
from tests.conftest import make_installation
from tests.emergency_lane_support import build, fresh, lane_workspace, seeded, started_by_round
from tests.factories import new_unit, started_ids
from tests.pipeline.test_slots_per_account import kit, repos
from tests.tick_pass import isolate

pytestmark = pytest.mark.usefixtures("scripted_engine")

NOW = datetime(2030, 1, 1, 12, tzinfo=UTC)
TTL = timedelta(minutes=5)

Unit = tuple[StoredUnit, UnitState]


@pytest.fixture(autouse=True)
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate(monkeypatch)


def held(count: int, *, repo: str = "app") -> list[Unit]:
    return [build(f"run{n}/1", repo=repo) for n in range(count)]


def waiting(count: int, **fields: object) -> list[Unit]:
    return [fresh(f"wait{n}/1", **fields) for n in range(count)]


def lane_workspace_of(tmp_path: Path, *, workers: int, places: int, extra: int) -> Installation:
    return lane_workspace(tmp_path, workers=workers, places=places, extra=extra)


def accounts_workspace(tmp_path: Path, **_: int) -> Installation:
    return make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        repos=repos(tmp_path, {"app": "kit"}),
        runtimes={"claude_code": {"accounts": kit(tmp_path, max_units_in_progress=1)}},
        project_limits={"max_concurrent_stacks": 4, "max_units_in_progress": 5},
    )


# What each scenario seeds, its workspace and the ids a round and admission both start.
SCENARIOS: dict[str, tuple[Callable[..., Installation], dict, list[Unit], list[str]]] = {
    "a free project": (
        lane_workspace_of,
        dict(workers=2, places=5, extra=0),
        [*waiting(3)],
        ["wait0/1", "wait1/1"],
    ),
    "a project with one worker left": (
        lane_workspace_of,
        dict(workers=2, places=5, extra=0),
        [*held(1), *waiting(3)],
        ["wait0/1"],
    ),
    "a full project": (
        lane_workspace_of,
        dict(workers=2, places=5, extra=0),
        [*held(2), *waiting(2)],
        [],
    ),
    "units in progress at the project's limit": (
        lane_workspace_of,
        dict(workers=4, places=2, extra=0),
        [*held(2), *waiting(2)],
        [],
    ),
    "a full project and a priority-zero unit": (
        lane_workspace_of,
        dict(workers=2, places=5, extra=1),
        [*held(2), fresh("zero/1", priority=0), fresh("one/1", priority=1)],
        ["zero/1"],
    ),
    "an account at its own limit": (
        accounts_workspace,
        dict(),
        [*held(1), *waiting(2)],
        [],
    ),
}


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_the_round_and_admission_start_the_same_units(tmp_path: Path, name: str) -> None:
    make, kwargs, units, expected = SCENARIOS[name]
    inst = make(tmp_path, **kwargs)
    store = seeded(inst, tmp_path, units)
    locked = [unit.id for unit, state in units if state == RUNNING]
    for uid in locked:
        lock_held_by(inst, f"spec/{uid}", os.getpid())
    candidates = [store.get(unit.id) for unit, state in units if state == PLANNED]

    started = started_by_round(inst, store, building=locked)
    admitted = admit(inst, store, candidates, worker="w1", now=NOW, ttl=TTL)

    assert sorted(started) == sorted(unit.id for unit in admitted) == sorted(expected)


def test_a_paused_unit_holds_a_place_and_no_worker_for_ready_units_and_for_admission(
    tmp_path: Path,
) -> None:
    inst = lane_workspace(tmp_path, workers=1, places=2, extra=0)
    store = seeded(inst, tmp_path, [build("p/1"), *waiting(2)])
    store.set_usage_pause("p/1", NOW + timedelta(hours=1))
    candidates = [store.get(unit.id) for unit, _ in waiting(2)]

    # The round would resume the paused unit first (its thread is what ends the pause), so the
    # rule the round applies to new units is asked directly.
    started = started_ids(store.all(), slots=1, max_units_in_progress=2, no_worker={"p/1"})
    admitted = admit(inst, store, candidates, worker="w1", now=NOW, ttl=TTL)

    # It takes no worker, and one place of the two: one more unit starts, and no more.
    assert [unit.id for unit in admitted] == started == ["wait0/1"]


def test_per_project_counts_match_the_pools_in_memory_counts() -> None:
    units = [
        new_unit("a/1", repo="app", branch="spec/a/1"),
        new_unit("a/2", repo="app", branch="spec/a/2"),
        new_unit("b/1", repo="platform", branch="spec/b/1"),
    ]
    units = [unit.model_copy(update={"state": RUNNING}) for unit in units]
    held_ids = {unit.id for unit in units}

    pool = slot_occupancy(units, held_ids, ())
    pure = occupied(units, locks={unit.branch for unit in units}, leases=(), now=NOW)

    assert {key: len(ids) for key, ids in pool.items()} == dict(pure.workers)


def test_the_pure_function_over_the_stores_facts_reports_the_rounds_free_workers(
    tmp_path: Path,
) -> None:
    inst = lane_workspace(tmp_path, workers=3, places=9, extra=0)
    units = [*held(1), build("rev/1", IN_REVIEW), *waiting(4)]
    store = seeded(inst, tmp_path, units)
    lock_held_by(inst, "spec/run0/1", os.getpid())

    started = started_by_round(inst, store, building=["run0/1"])
    found = current_occupancy(inst, store.all(), NOW)
    limits = limits_of(inst)

    assert len(started) == free(found, limits, project_key(store.get("wait0/1"))) == 2


def test_limits_follow_the_installation(tmp_path: Path) -> None:
    inst = lane_workspace(tmp_path, workers=3, places=9, extra=2)

    assert limits_of(inst) == Limits(stacks=3, emergency_extra=2, in_progress=9)
