"""A unit never stays `running` after its run is gone.

A `running` unit whose branch lock names a dead process is failed at the start
of a pass, so `abk requeue` can move it. A live holder, a missing or unreadable
lock, a unit with a thread to resume from, one the pass is holding and any
other state are left alone. Recording an outcome retries once when the store
cannot be read, and says so when it still cannot.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.cli.pipeline import reconcile_running, resumable_units
from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import RETRY_BY, UnitStore
from agent_build_kit.pipeline.units import FAILED, HELD, IN_REVIEW, PLANNED, RUNNING, UnitState
from tests.branch_lock_fakes import dead_pid, lock_held_by
from tests.conftest import make_installation
from tests.factories import unit

NOTE = "the run ended without recording its outcome"
# A literal on purpose: it pins the cause the history records, which a rename must not change.
LOST_RUN = "lost run"


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    installation = make_installation(tmp_path / "planning")
    (installation.root / "abk.yaml").write_text(dump(installation.config))
    monkeypatch.chdir(installation.root)
    return installation


@pytest.fixture
def store(inst: Installation) -> UnitStore:
    return UnitStore(inst.state_dir / "units.json")


def stored(store: UnitStore, uid: str, state: UnitState = RUNNING) -> str:
    """Plan `uid`, put it in `state` on its branch, and return the branch."""
    branch = f"spec/{uid}"
    store.upsert([unit(uid)])
    store.set_state(uid, state, branch=branch)
    return branch


def with_lost_run_spent(store: UnitStore, uid: str) -> None:
    """Record the unit's one retry for a lost run, as a first loss would have."""
    store.record_retry(uid, LOST_RUN, "lost run: its run ended without an outcome")


def test_a_first_lost_run_is_requeued_to_resume_and_not_failed(
    inst: Installation, store: UnitStore
) -> None:
    branch = stored(store, "add-marker/1")
    lock_held_by(inst, branch, dead_pid())

    reconcile_running(inst, store)

    after = store.get("add-marker/1")
    assert after.state == PLANNED
    assert after.note != NOTE
    retries = [e for e in store.history("add-marker/1") if e.get("by") == RETRY_BY]
    assert len(retries) == 1
    assert str(retries[0]["note"]).startswith(LOST_RUN)
    assert store.retry_spent("add-marker/1", LOST_RUN)


def test_a_running_unit_whose_lost_run_retry_is_spent_is_failed_and_can_be_requeued(
    inst: Installation, store: UnitStore
) -> None:
    branch = stored(store, "add-marker/1")
    with_lost_run_spent(store, "add-marker/1")
    lock_held_by(inst, branch, dead_pid())

    reconcile_running(inst, store)

    after = store.get("add-marker/1")
    assert after.state == FAILED
    assert after.note == NOTE
    assert main(["requeue", "add-marker/1"]) == 0
    assert store.get("add-marker/1").state == PLANNED
    assert not store.retry_spent("add-marker/1", LOST_RUN)
    store.set_state("add-marker/1", RUNNING)

    reconcile_running(inst, store)

    assert store.get("add-marker/1").state == PLANNED
    assert store.retry_spent("add-marker/1", LOST_RUN)


def test_a_running_unit_with_a_live_holder_is_unchanged(
    inst: Installation, store: UnitStore
) -> None:
    branch = stored(store, "add-marker/1")
    lock_held_by(inst, branch, os.getpid())

    reconcile_running(inst, store)

    assert store.get("add-marker/1").state == RUNNING


def test_a_running_unit_with_no_lock_is_unchanged_and_reported(
    inst: Installation, store: UnitStore, capsys: pytest.CaptureFixture[str]
) -> None:
    stored(store, "add-marker/1")

    reconcile_running(inst, store)

    assert store.get("add-marker/1").state == RUNNING
    assert "add-marker/1" in capsys.readouterr().out


def test_a_running_unit_with_a_thread_is_left_to_resume(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    branch = stored(store, "add-marker/1")
    lock_held_by(inst, branch, dead_pid())
    monkeypatch.setattr("agent_build_kit.run_support.has_thread", lambda inst, unit_id: True)

    reconcile_running(inst, store)

    assert store.get("add-marker/1").state == RUNNING
    resumable = resumable_units(inst, store.all(), only=frozenset())
    assert [unit.id for unit in resumable] == ["add-marker/1"]


def test_a_running_unit_in_flight_is_left_alone(inst: Installation, store: UnitStore) -> None:
    branch = stored(store, "add-marker/1")
    lock_held_by(inst, branch, dead_pid())

    reconcile_running(inst, store, in_flight={"add-marker/1"})

    assert store.get("add-marker/1").state == RUNNING


def test_a_running_unit_whose_lock_is_empty_is_unchanged(
    inst: Installation, store: UnitStore
) -> None:
    branch = stored(store, "add-marker/1")
    lock_held_by(inst, branch, os.getpid())
    (lock,) = (inst.state_dir / "locks").glob("*.lock")
    lock.write_text("")

    reconcile_running(inst, store)

    assert store.get("add-marker/1").state == RUNNING


@pytest.mark.parametrize("state", [PLANNED, IN_REVIEW, HELD, FAILED])
def test_a_unit_in_another_state_is_untouched_whatever_its_lock_says(
    inst: Installation, store: UnitStore, state: UnitState
) -> None:
    branch = stored(store, "add-marker/1", state)
    lock_held_by(inst, branch, dead_pid())
    before = store.get("add-marker/1")

    reconcile_running(inst, store)

    assert store.get("add-marker/1") == before


def test_only_the_unit_whose_holder_is_dead_is_failed(inst: Installation, store: UnitStore) -> None:
    gone = stored(store, "add-marker/1")
    with_lost_run_spent(store, "add-marker/1")
    alive = stored(store, "add-marker/2")
    lock_held_by(inst, gone, dead_pid())
    lock_held_by(inst, alive, os.getpid())
    fresh = stored(store, "add-marker/3")
    lock_held_by(inst, fresh, dead_pid())

    reconcile_running(inst, store)

    assert store.get("add-marker/1").state == FAILED
    assert store.get("add-marker/2").state == RUNNING
    assert store.get("add-marker/3").state == PLANNED


def test_an_outcome_is_recorded_when_the_first_read_fails_and_the_second_succeeds(
    store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored(store, "add-marker/1")
    good = store.path.read_text()
    store.path.write_text('{"units": [')
    waits: list[float] = []

    def mend(seconds: float) -> None:
        waits.append(seconds)
        store.path.write_text(good)

    monkeypatch.setattr(time, "sleep", mend)

    store.set_state("add-marker/1", FAILED)

    assert len(waits) == 1
    assert store.get("add-marker/1").state == FAILED


def test_two_failed_reads_log_the_unit_as_stranded_and_raise_as_before(
    store: UnitStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stored(store, "add-marker/1")
    store.path.write_text('{"units": [')
    waits: list[float] = []
    monkeypatch.setattr(time, "sleep", waits.append)

    with pytest.raises(ValueError, match="could not be read"):
        store.set_state("add-marker/1", FAILED)

    assert len(waits) == 1
    said = capsys.readouterr().out
    assert "add-marker/1" in said
    assert "stranded" in said
