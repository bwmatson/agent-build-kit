"""Admission counts, checks and marks under one lock, so two admitters never admit past a limit,
and a `starting` marker that expired with no lock held frees its unit and its slot."""

import threading
from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli.pipeline import reclaim_stranded
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.admission import admit
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import PLANNED, RUNNING
from tests import fake_clock
from tests.emergency_lane_support import lane_workspace
from tests.factories import new_unit

TTL = timedelta(seconds=60)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> fake_clock.FakeClock:
    return fake_clock.install(monkeypatch)


def one_slot(tmp_path: Path, ids: list[str]) -> tuple[Installation, Path]:
    inst = lane_workspace(tmp_path, workers=1, places=5, extra=0)
    path = tmp_path / "units.json"
    UnitStore(path).upsert([new_unit(uid, repo="app") for uid in ids])
    return inst, path


def test_admission_marks_the_admitted_unit_starting_for_its_worker(
    tmp_path: Path, clock: fake_clock.FakeClock
) -> None:
    inst, path = one_slot(tmp_path, ["a/1"])
    store = UnitStore(path)

    admitted = admit(inst, store, [store.get("a/1")], worker="w1", ttl=TTL)

    assert [unit.id for unit in admitted] == ["a/1"]
    marker = store.get("a/1").starting
    assert marker is not None
    assert (marker.worker, marker.until) == ("w1", clock.now() + TTL)


def test_admission_stops_at_the_free_slots(tmp_path: Path, clock: fake_clock.FakeClock) -> None:
    inst, path = one_slot(tmp_path, ["a/1", "b/1"])
    store = UnitStore(path)

    admitted = admit(inst, store, [store.get("a/1"), store.get("b/1")], worker="w1", ttl=TTL)

    assert [unit.id for unit in admitted] == ["a/1"]
    assert store.get("b/1").starting is None


def test_a_marked_unit_holds_its_slot_against_the_next_admitter(
    tmp_path: Path, clock: fake_clock.FakeClock
) -> None:
    inst, path = one_slot(tmp_path, ["a/1", "b/1"])
    admit(inst, UnitStore(path), [UnitStore(path).get("a/1")], worker="w1", ttl=TTL)
    later = UnitStore(path)

    assert admit(inst, later, [later.get("b/1")], worker="w2", ttl=TTL) == []


def test_an_expired_marker_frees_the_slot_for_the_next_admitter(
    tmp_path: Path, clock: fake_clock.FakeClock
) -> None:
    inst, path = one_slot(tmp_path, ["a/1", "b/1"])
    first = UnitStore(path)
    admit(inst, first, [first.get("a/1")], worker="w1", ttl=TTL)
    clock.advance(TTL.total_seconds() + 1)
    later = UnitStore(path)

    admitted = admit(inst, later, [later.get("b/1")], worker="w2", ttl=TTL)

    assert [unit.id for unit in admitted] == ["b/1"]


def test_two_admitters_racing_over_one_free_slot_admit_one_unit(
    tmp_path: Path, clock: fake_clock.FakeClock
) -> None:
    inst, path = one_slot(tmp_path, ["a/1", "b/1"])
    start = threading.Barrier(2)
    admitted: dict[str, list[str]] = {}

    def racer(uid: str) -> None:
        store = UnitStore(path)
        unit = store.get(uid)
        start.wait()
        admitted[uid] = [each.id for each in admit(inst, store, [unit], worker=uid, ttl=TTL)]

    threads = [threading.Thread(target=racer, args=(uid,)) for uid in ("a/1", "b/1")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(uid for ids in admitted.values() for uid in ids) in (["a/1"], ["b/1"])
    marked = [unit.id for unit in UnitStore(path).all() if unit.starting is not None]
    assert len(marked) == 1


def test_admission_takes_the_admission_lock_file(
    tmp_path: Path, clock: fake_clock.FakeClock
) -> None:
    inst, path = one_slot(tmp_path, ["a/1"])
    store = UnitStore(path)

    admit(inst, store, [store.get("a/1")], worker="w1", ttl=TTL)

    assert (inst.state_dir / "locks" / "admission.lock").exists()


def test_a_unit_whose_marker_expired_and_holds_no_lock_is_planned_again(
    tmp_path: Path, clock: fake_clock.FakeClock
) -> None:
    inst, path = one_slot(tmp_path, ["a/1"])
    store = UnitStore(path)
    admit(inst, store, [store.get("a/1")], worker="w1", ttl=TTL)
    store.set_state("a/1", RUNNING, branch="spec/a/1")
    clock.advance(TTL.total_seconds() + 1)

    reclaim_stranded(inst, store)

    unit = store.get("a/1")
    assert unit.state == PLANNED
    assert unit.starting is None


def test_a_unit_with_an_unexpired_marker_is_not_reclaimed(
    tmp_path: Path, clock: fake_clock.FakeClock
) -> None:
    inst, path = one_slot(tmp_path, ["a/1"])
    store = UnitStore(path)
    admit(inst, store, [store.get("a/1")], worker="w1", ttl=TTL)
    store.set_state("a/1", RUNNING, branch="spec/a/1")
    clock.advance(TTL.total_seconds() - 1)

    reclaim_stranded(inst, store)

    assert store.get("a/1").state == RUNNING
