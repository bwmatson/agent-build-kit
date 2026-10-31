"""Admission counts, checks and marks under one lock: two admitters over one free slot admit one
unit, and a marker that lapses with no lock held returns its unit to `planned`."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

from agent_build_kit.cli.pipeline import reclaim_stranded
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.admission import admit
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import PLANNED, RUNNING
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.conftest import make_installation
from tests.factories import new_unit

TTL = timedelta(minutes=10)


def one_slot(tmp_path: Path) -> Installation:
    return make_installation(tmp_path, project_limits=dict(max_concurrent_stacks=1))


def store_of(inst: Installation, *ids: str) -> UnitStore:
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert([new_unit(uid) for uid in ids])
    return store


def test_two_admitters_racing_over_one_free_slot_admit_one_unit(tmp_path):
    inst = one_slot(tmp_path)
    store_of(inst, "a/1", "b/1")
    start = Barrier(2)

    def admitter(worker: str) -> list[str]:
        mine = UnitStore(inst.state_dir / "units.json")
        start.wait(timeout=10)
        return [
            unit.id
            for unit in admit(inst, mine, mine.all(), worker=worker, now=datetime.now(UTC), ttl=TTL)
        ]

    with ThreadPoolExecutor(max_workers=2) as pool:
        admitted = [id_ for ids in pool.map(admitter, ["w1", "w2"]) for id_ in ids]

    assert len(admitted) == 1
    marked = [u.id for u in UnitStore(inst.state_dir / "units.json").all() if u.starting]
    assert marked == admitted


def test_an_admitted_unit_carries_its_workers_marker_until_it_lapses(tmp_path):
    inst = one_slot(tmp_path)
    store = store_of(inst, "a/1")
    now = datetime.now(UTC)

    admit(inst, store, store.all(), worker="w1", now=now, ttl=TTL)

    marker = store.get("a/1").starting
    assert marker is not None
    assert (marker.worker, marker.until) == ("w1", now + TTL)


def test_a_marked_unit_holds_its_slot_against_the_next_admission(tmp_path):
    inst = one_slot(tmp_path)
    store = store_of(inst, "a/1", "b/1")
    now = datetime.now(UTC)
    [first] = admit(inst, store, [store.get("a/1")], worker="w1", now=now, ttl=TTL)

    later = admit(inst, store, [store.get("b/1")], worker="w2", now=now, ttl=TTL)

    assert (first.id, later) == ("a/1", [])


def test_a_live_branch_lock_holds_a_slot_too(tmp_path):
    inst = one_slot(tmp_path)
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert([new_unit("a/1"), new_unit("b/1")])
    store.set_state("a/1", RUNNING, branch="spec/a/1")

    with branch_lock("spec/a/1", root=inst.locks_dir):
        admitted = admit(
            inst, store, [store.get("b/1")], worker="w1", now=datetime.now(UTC), ttl=TTL
        )

    assert admitted == []


def test_a_marker_that_lapsed_with_no_lock_returns_its_unit_to_planned(tmp_path):
    inst = one_slot(tmp_path)
    store = store_of(inst, "a/1")
    long_ago = datetime.now(UTC) - timedelta(hours=2)
    admit(inst, store, store.all(), worker="w1", now=long_ago, ttl=TTL)
    store.set_state("a/1", RUNNING, branch="spec/a/1")

    reclaim_stranded(inst, store)

    unit = store.get("a/1")
    assert (unit.state, unit.starting) == (PLANNED, None)


def test_an_unexpired_marker_keeps_its_unit_while_its_worker_takes_the_lock(tmp_path):
    inst = one_slot(tmp_path)
    store = store_of(inst, "a/1")
    admit(inst, store, store.all(), worker="w1", now=datetime.now(UTC), ttl=timedelta(hours=1))
    store.set_state("a/1", RUNNING, branch="spec/a/1")

    reclaim_stranded(inst, store)

    unit = store.get("a/1")
    assert unit.state == RUNNING
    assert unit.starting is not None
