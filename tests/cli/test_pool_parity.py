"""The thread pool's admission and the pure occupancy function agree on the same fixtures."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_build_kit.cli.pipeline import slot_occupancy
from agent_build_kit.pipeline.admission import admit
from agent_build_kit.pipeline.occupancy import Limits, free, occupied
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import RUNNING, ProjectKey, project_key
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.conftest import make_installation
from tests.factories import new_unit, started_ids

NOW = datetime(2030, 1, 1, 12, tzinfo=UTC)


def running(uid: str, repo: str):
    return new_unit(uid, repo=repo, branch=f"spec/{uid}").model_copy(update={"state": RUNNING})


def test_per_project_counts_match_the_pools_in_memory_counts():
    units = [running("a/1", "app"), running("a/2", "app"), running("b/1", "platform")]
    held = {unit.id for unit in units}

    pool = slot_occupancy(units, held, ())
    pure = occupied(units, locks={unit.branch for unit in units}, leases=(), now=NOW)

    assert {key: len(ids) for key, ids in pool.items()} == dict(pure.projects)


def test_free_slots_match_the_workers_ready_units_leaves():
    units = [
        running("a/1", "app"),
        new_unit("a/2", repo="app"),
        new_unit("a/3", repo="app"),
        new_unit("b/1", repo="platform"),
    ]
    stacks = 2
    found = occupied(units, locks={"spec/a/1"}, leases=(), now=NOW)

    limits = Limits(stacks=stacks)
    pure = {repo: free(found, limits, ProjectKey(repo=repo)) for repo in ("app", "platform")}
    started = started_ids(units, slots=stacks)

    assert pure == {"app": 1, "platform": 2}
    assert [uid for uid in started if uid.startswith("a/")] == ["a/2"]


def test_admission_starts_what_ready_units_starts(tmp_path: Path):
    inst = make_installation(tmp_path, project_limits=dict(max_concurrent_stacks=2))
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert([new_unit(uid) for uid in ("a/1", "a/2", "a/3")])
    store.set_state("a/1", RUNNING, branch="spec/a/1")
    graph = store.all()

    waiting = [u for u in graph if u.id != "a/1"]

    with branch_lock("spec/a/1", root=inst.locks_dir):
        admitted = admit(inst, store, waiting, worker="w1", now=NOW, ttl=timedelta(minutes=5))

    assert [u.id for u in admitted] == started_ids(graph, slots=2)
    assert {project_key(u) for u in admitted} == {ProjectKey(repo="app")}
