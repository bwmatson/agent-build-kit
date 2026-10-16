"""A unit queued behind the tier 2 lock waits for as long as it takes, says who it waits
for, and the lock names its holder (spec: tier2-lock-wait-holds-the-unit).

The lock is held through `flock` from another file handle, and the clock the wait reads
moves only as the waiter sleeps, so no test waits."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.cli.pipeline import StackBusy, verify_one
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import wiring
from agent_build_kit.pipeline.e2e import stack_lock
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.verify import Verification
from tests.factories import unit
from tests.fake_clock import span_lines
from tests.tier2_lock_fakes import (
    STEP,
    Foreign,
    Ran,
    SleepingTime,
    dead_pid,
    install_clock,
    record_line,
    tier2_runner,
)

HOUR = 3600
BUSY = "e2e-test is busy"


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> SleepingTime:
    return install_clock(monkeypatch)


def runner(
    workspace: Installation,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    log: list[str],
) -> tuple[wiring.UnitRunner, Ran]:
    store = UnitStore(tmp_path / "units.json")
    return tier2_runner(workspace, store, monkeypatch, log, unit(repo="app"))


def tree(tmp_path: Path) -> Path:
    cwd = tmp_path / "tree"
    cwd.mkdir()
    return cwd


def test_a_wait_without_a_deadline_outlasts_the_old_hour(
    tmp_path: Path, clock: SleepingTime
) -> None:
    lock = tmp_path / "tier2.lock"
    other = Foreign(lock)
    clock.release_at(2 * HOUR, other.release)
    taken = False

    with stack_lock(lock):
        taken = True

    assert taken
    assert clock.elapsed() >= 2 * HOUR


def test_a_tier_2_run_queued_behind_a_long_holder_runs_and_returns_its_result(
    workspace: Installation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: SleepingTime
) -> None:
    lock = workspace.state_dir / "tier2.lock"
    other = Foreign(lock)
    clock.release_at(2 * HOUR, other.release)
    built, ran = runner(workspace, tmp_path, monkeypatch, [])

    ok, _ = built.run_e2e(cwd=tree(tmp_path))

    assert ok
    assert ran.record_seen is not None
    assert clock.elapsed() >= 2 * HOUR


def test_the_wait_is_logged_at_once_and_at_each_interval_with_the_holder_and_its_age(
    workspace: Installation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: SleepingTime
) -> None:
    lock = workspace.state_dir / "tier2.lock"
    other = Foreign(lock, unit="other/1", pid=os.getpid(), age=40 * 60)
    clock.release_at(650, other.release)
    log: list[str] = []
    built, _ = runner(workspace, tmp_path, monkeypatch, log)

    built.run_e2e(cwd=tree(tmp_path))

    waiting = [line for line in log if BUSY in line]
    # at once, then after five minutes and after ten
    assert len(waiting) == 3
    assert all("other/1" in line for line in waiting)
    for line, held_for, waited in zip(
        waiting, ("40m 0s", "45m 0s", "50m 0s"), ("0m 0s", "5m 0s", "10m 0s"), strict=True
    ):
        assert f"held for {held_for})" in line
        assert line.endswith(f"waited {waited}")


def test_a_wait_that_ends_records_one_span_with_the_seconds_waited(
    workspace: Installation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: SleepingTime
) -> None:
    lock = workspace.state_dir / "tier2.lock"
    other = Foreign(lock, pid=os.getpid())
    clock.release_at(400, other.release)
    built, _ = runner(workspace, tmp_path, monkeypatch, [])

    built.run_e2e(cwd=tree(tmp_path))

    waited = [s for s in span_lines(workspace) if s.get("waited") == "e2e_lock"]
    assert len(waited) == 1
    assert waited[0]["unit"] == "add-marker/1"
    assert waited[0]["change"] == "add-marker"
    assert waited[0]["duration_ms"] == pytest.approx(clock.elapsed() * 1000, abs=STEP * 1000)


def test_the_holder_writes_its_unit_process_and_start_into_the_file_and_clears_it(
    tmp_path: Path, clock: SleepingTime
) -> None:
    lock = tmp_path / "tier2.lock"

    with stack_lock(lock, holder="add-marker/1"):
        record = json.loads(lock.read_text())

    assert record["unit"] == "add-marker/1"
    assert record["pid"] == os.getpid()
    assert datetime.fromisoformat(record["since"]).utcoffset() is not None
    assert lock.read_text() == ""


def test_the_record_is_cleared_when_the_body_raises(tmp_path: Path, clock: SleepingTime) -> None:
    lock = tmp_path / "tier2.lock"

    with pytest.raises(ValueError):  # noqa: PT012 — the raise is the point
        with stack_lock(lock, holder="add-marker/1"):
            raise ValueError("boom")

    assert lock.read_text() == ""


def test_a_lock_taken_at_once_is_held_under_the_units_id_with_no_wait_logged_or_recorded(
    workspace: Installation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: SleepingTime
) -> None:
    log: list[str] = []
    built, ran = runner(workspace, tmp_path, monkeypatch, log)

    ok, _ = built.run_e2e(cwd=tree(tmp_path))

    assert ok
    assert ran.record_seen is not None
    assert json.loads(ran.record_seen)["unit"] == "add-marker/1"
    assert clock.elapsed() == 0
    assert not [line for line in log if BUSY in line]
    assert [s for s in span_lines(workspace) if s.get("waited") == "e2e_lock"] == []


def test_a_free_lock_with_a_dead_holders_record_is_logged_stale_and_overwritten(
    workspace: Installation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: SleepingTime
) -> None:
    lock = workspace.state_dir / "tier2.lock"
    gone = dead_pid()
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(record_line("other/1", gone))
    log: list[str] = []
    built, ran = runner(workspace, tmp_path, monkeypatch, log)

    ok, _ = built.run_e2e(cwd=tree(tmp_path))

    assert ok
    stale = [line for line in log if "stale" in line]
    assert len(stale) == 1
    assert "other/1" in stale[0]
    assert str(gone) in stale[0]
    assert ran.record_seen is not None
    assert json.loads(ran.record_seen)["unit"] == "add-marker/1"
    assert clock.elapsed() == 0
    assert not [line for line in log if BUSY in line]


def test_a_held_lock_whose_recorded_process_is_gone_is_not_broken(
    workspace: Installation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: SleepingTime
) -> None:
    lock = workspace.state_dir / "tier2.lock"
    gone = dead_pid()
    other = Foreign(lock, unit="other/1", pid=gone)
    clock.release_at(400, other.release)
    log: list[str] = []
    built, ran = runner(workspace, tmp_path, monkeypatch, log)

    ok, _ = built.run_e2e(cwd=tree(tmp_path))

    assert ok
    # it ran only once the holder let go, and said why it kept waiting
    assert clock.elapsed() >= 400
    gone_lines = [line for line in log if str(gone) in line and "gone" in line]
    assert gone_lines
    assert "other/1" in gone_lines[0]


def test_a_caller_with_its_own_wait_holds_under_its_name_and_still_gets_busy(
    workspace: Installation, monkeypatch: pytest.MonkeyPatch, clock: SleepingTime
) -> None:
    lock = workspace.state_dir / "tier2.lock"
    other = Foreign(lock, pid=os.getpid())
    with pytest.raises(StackBusy):
        verify_one(workspace, "add-marker", [], wait=30)
    other.release()

    seen: list[str] = []

    def verified(change: str, units: list, **kwargs: object) -> Verification:
        seen.append(lock.read_text())
        return Verification(change=change, passed=True)

    monkeypatch.setattr(cli, "verify_change", verified)
    verify_one(workspace, "add-marker", [], wait=30)

    assert json.loads(seen[0])["unit"] == "verify add-marker"
