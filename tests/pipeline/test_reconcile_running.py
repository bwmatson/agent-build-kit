"""A unit never stays `running` after its run is gone.

A `running` unit whose branch lock names a dead process is failed at the start
of a pass, so `abk requeue` can move it. A live holder, a missing lock and any
other state are left alone. Recording an outcome retries once when the store
cannot be read, and says so when it still cannot.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.cli.pipeline import reconcile_running
from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import FAILED, HELD, IN_REVIEW, PLANNED, RUNNING, UnitState
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.conftest import make_installation
from tests.factories import unit

NOTE = "the run ended without recording its outcome"


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    installation = make_installation(tmp_path / "planning")
    (installation.root / "abk.yaml").write_text(dump(installation.config))
    monkeypatch.chdir(installation.root)
    return installation


@pytest.fixture
def store(inst: Installation) -> UnitStore:
    return UnitStore(inst.state_dir / "units.json")


def dead_pid() -> int:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def lock_held_by(inst: Installation, branch: str, pid: int) -> None:
    """The lock file `branch_lock` writes, naming `pid` as its holder."""
    locks = inst.state_dir / "locks"
    before = set(locks.glob("*.lock")) if locks.exists() else set()
    with branch_lock(branch, root=locks):
        (made,) = set(locks.glob("*.lock")) - before
    made.write_text(json.dumps({"pid": pid, "branch": branch, "at": "2030-01-01T09:00:00+00:00"}))


def stored(store: UnitStore, uid: str, state: UnitState = RUNNING) -> str:
    """Plan `uid`, put it in `state` on its branch, and return the branch."""
    branch = f"spec/{uid}"
    store.upsert([unit(uid)])
    store.set_state(uid, state, branch=branch)
    return branch


def test_a_running_unit_whose_holder_is_dead_is_failed_and_can_be_requeued(
    inst: Installation, store: UnitStore
) -> None:
    branch = stored(store, "add-marker/1")
    lock_held_by(inst, branch, dead_pid())

    reconcile_running(inst, store)

    after = store.get("add-marker/1")
    assert after.state == FAILED
    assert after.note == NOTE
    assert main(["requeue", "add-marker/1"]) == 0
    assert store.get("add-marker/1").state == PLANNED


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
    alive = stored(store, "add-marker/2")
    lock_held_by(inst, gone, dead_pid())
    lock_held_by(inst, alive, os.getpid())

    reconcile_running(inst, store)

    assert store.get("add-marker/1").state == FAILED
    assert store.get("add-marker/2").state == RUNNING


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
    caplog: pytest.LogCaptureFixture,
) -> None:
    stored(store, "add-marker/1")
    store.path.write_text('{"units": [')
    waits: list[float] = []
    monkeypatch.setattr(time, "sleep", waits.append)

    with pytest.raises(ValueError, match="could not be read"):
        store.set_state("add-marker/1", FAILED)

    assert len(waits) == 1
    said = capsys.readouterr().out + caplog.text
    assert "add-marker/1" in said
    assert "stranded" in said
