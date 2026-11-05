"""`abk status` says when a settling unit's late check waits for a unit-test slot, and since when
(spec: merged-waits-for-ci); the line is gone once the run has its slot."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.unit_store import Pull, UnitStore
from agent_build_kit.pipeline.unit_test_slots import unit_test_slot
from agent_build_kit.pipeline.units import SETTLING
from tests.conftest import make_installation, run_status
from tests.factories import new_unit
from tests.unit_test_slot_fakes import live_waiter

MERGED_AT = datetime(2026, 10, 27, 11, 43, tzinfo=UTC)
WAITING_SINCE = datetime(2026, 10, 27, 12, 5, tzinfo=UTC)
LINE = f"settling: late check waiting for a unit-test slot since {WAITING_SINCE:%Y-%m-%d %H:%M} UTC"


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    inst = make_installation(tmp_path, planning={"state_dir": "."})
    inst.locks_dir.mkdir(parents=True, exist_ok=True)
    return inst


@pytest.fixture
def store(inst: Installation) -> UnitStore:
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert([new_unit("add-marker/1")])
    store.set_state("add-marker/1", SETTLING, pr=4, branch="spec/add-marker/1")
    store.set_pulls(
        "add-marker/1",
        (Pull(number=4, branch="spec/add-marker/1", merged_at=MERGED_AT, merge_sha="abc123"),),
    )
    return store


def test_a_settling_unit_whose_late_check_waits_shows_the_wait_and_since_when(
    inst: Installation,
    store: UnitStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with live_waiter(inst.locks_dir, "1-aaaa", "add-marker/1", since=WAITING_SINCE, rank=(-1,)):
        lines = run_status(inst, monkeypatch, capsys)

    line = next(line for line in lines if "add-marker/1" in line and "settling:" in line)
    assert LINE in line


def test_once_the_run_has_its_slot_the_unit_shows_its_late_check_running(
    inst: Installation,
    store: UnitStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    turn = events.build_late_check_turn(inst.locks_dir)
    with turn(store.get("add-marker/1")), unit_test_slot(inst.locks_dir, 1, holder="add-marker/1"):
        lines = run_status(inst, monkeypatch, capsys)

    assert not any("late check waiting" in line for line in lines)
    line = next(line for line in lines if "add-marker/1" in line and "settling:" in line)
    assert "settling: late check running on the default branch" in line


def test_with_no_late_check_the_unit_waits_for_its_checks(
    inst: Installation,
    store: UnitStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lines = run_status(inst, monkeypatch, capsys)

    assert any("add-marker/1" in line and "settling: waiting for" in line for line in lines)


def test_a_waiting_run_of_another_unit_says_nothing_of_the_settling_one(
    inst: Installation,
    store: UnitStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with live_waiter(inst.locks_dir, "1-aaaa", "other/1", since=WAITING_SINCE, rank=(0, 2)):
        lines = run_status(inst, monkeypatch, capsys)

    assert not any("late check waiting" in line for line in lines)
