"""Admission counts, checks and marks under one lock: two admitters over one free slot admit one
unit, a marker that lapses with no lock held returns its unit to `planned`, and the limits it
holds a candidate to are the pool's: workers, units in progress per project or account, and the
emergency lane's places."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest

from agent_build_kit.cli.pipeline import reclaim_stranded
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import emergency_lane
from agent_build_kit.pipeline.admission import admit
from agent_build_kit.pipeline.file_lock import LockTimeout, file_lock
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import PLANNED, RUNNING
from agent_build_kit.pipeline.workspaces import branch_lock
from agent_build_kit.settings import settings
from tests.conftest import make_installation
from tests.emergency_lane_support import lane_workspace
from tests.factories import new_unit
from tests.pipeline.test_slots_per_account import kit, repos

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


def test_admission_waits_on_the_admission_lock_and_marks_nothing_without_it(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    inst = one_slot(tmp_path)
    store = store_of(inst, "a/1")
    monkeypatch.setattr(settings, "lock_wait_seconds", 0.2)

    with file_lock(inst.locks_dir / "admission.lock"):
        with pytest.raises(LockTimeout):
            admit(inst, store, store.all(), worker="w1", now=datetime.now(UTC), ttl=TTL)

    assert store.get("a/1").starting is None


def test_an_admitted_unit_carries_its_workers_marker_until_it_lapses(tmp_path):
    inst = one_slot(tmp_path)
    store = store_of(inst, "a/1")
    now = datetime.now(UTC)

    admit(inst, store, store.all(), worker="w1", now=now, ttl=TTL)

    marker = store.get("a/1").starting
    assert marker is not None
    assert (marker.worker, marker.until) == ("w1", now + TTL)


def test_a_marker_survives_a_replan(tmp_path):
    inst = one_slot(tmp_path)
    store = store_of(inst, "a/1")
    admit(inst, store, store.all(), worker="w1", now=datetime.now(UTC), ttl=TTL)

    store.upsert([new_unit("a/1")])

    assert store.get("a/1").starting is not None


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


def test_an_accounts_own_limit_holds_admission_below_the_project_limit(tmp_path):
    inst = make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        repos=repos(tmp_path, {"app": "kit"}),
        runtimes={"claude_code": {"accounts": kit(tmp_path, max_units_in_progress=1)}},
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert([new_unit("a/1", repo="app"), new_unit("b/1", repo="app")])
    now = datetime.now(UTC)
    admit(inst, store, [store.get("a/1")], worker="w1", now=now, ttl=TTL)

    assert admit(inst, store, [store.get("b/1")], worker="w2", now=now, ttl=TTL) == []


def test_the_units_in_progress_of_a_project_hold_back_a_new_unit_not_one_in_progress(tmp_path):
    inst = make_installation(
        tmp_path,
        project_limits=dict(max_concurrent_stacks=3, max_units_in_progress=1),
    )
    store = store_of(inst, "a/1", "b/1", "c/1")
    store.set_state("c/1", PLANNED, branch="spec/c/1")  # a rework: begun, so in progress
    now = datetime.now(UTC)
    admit(inst, store, [store.get("a/1")], worker="w1", now=now, ttl=TTL)

    admitted = admit(
        inst, store, [store.get("b/1"), store.get("c/1")], worker="w2", now=now, ttl=TTL
    )

    assert [unit.id for unit in admitted] == ["c/1"]


def test_a_paused_unit_counts_toward_the_units_in_progress_and_takes_no_worker(tmp_path):
    inst = make_installation(
        tmp_path, project_limits=dict(max_concurrent_stacks=1, max_units_in_progress=2)
    )
    store = store_of(inst, "a/1", "b/1", "c/1")
    store.set_state("a/1", RUNNING, branch="spec/a/1")
    store.set_usage_pause("a/1", datetime.now(UTC) + timedelta(hours=1))
    now = datetime.now(UTC)

    [second] = admit(inst, store, [store.get("b/1")], worker="w1", now=now, ttl=TTL)
    third = admit(inst, store, [store.get("c/1")], worker="w2", now=now, ttl=TTL)

    assert (second.id, third) == ("b/1", [])


def test_the_emergency_lane_admits_exactly_its_extra_places_past_a_full_project(tmp_path):
    inst = lane_workspace(tmp_path, workers=1, places=5, extra=2)
    ids = ["l1/1", "l2/1", "l3/1"]
    store = UnitStore(tmp_path / "units.json")
    store.upsert([new_unit("busy/1"), *(new_unit(uid) for uid in ids)])
    store.set_state("busy/1", RUNNING, branch="spec/busy/1")
    for uid in ids:
        emergency_lane.enter(inst.state_dir, store.get(uid))

    with branch_lock("spec/busy/1", root=inst.locks_dir):
        admitted = admit(
            inst,
            store,
            [store.get(uid) for uid in ids],
            worker="w1",
            now=datetime.now(UTC),
            ttl=TTL,
        )

    assert [unit.id for unit in admitted] == ["l1/1", "l2/1"]
