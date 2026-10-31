"""`abk status` shows a unit paused for usage as paused until a time and counts it, and `abk
explain` names the pause (spec: usage-pause-slots, a unit paused for usage is recorded and counts
as in progress)."""

from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli.explain_cmd import cmd_explain
from agent_build_kit.pipeline.unit_store import UnitStore
from tests import fake_clock
from tests.cli.usage_pause_support import pause_for_usage, unit, with_threads
from tests.conftest import make_installation, run_status, status_lines

PAUSED = ("paused0/1", "paused1/1")
HOURS = 3


def pause_both(clock: fake_clock.FakeClock):
    def record(store: UnitStore) -> None:
        store.upsert([unit(uid) for uid in PAUSED])
        for uid in PAUSED:
            pause_for_usage(store, uid, clock.now() + timedelta(hours=HOURS))

    return record


def test_status_shows_a_paused_unit_as_paused_for_usage_until_a_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clock = fake_clock.install(monkeypatch)
    with_threads(monkeypatch, *PAUSED)
    until = (clock.now() + timedelta(hours=HOURS)).astimezone()

    lines = status_lines(tmp_path, monkeypatch, capsys, record=pause_both(clock))

    shown = [line for line in lines if PAUSED[0] in line and "paused for usage" in line]
    assert shown
    assert f"until {until:%H:%M}" in shown[0]


def test_status_does_not_show_a_pause_whose_time_has_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clock = fake_clock.install(monkeypatch)
    with_threads(monkeypatch, *PAUSED)
    until = clock.now() + timedelta(hours=HOURS)

    def record(store: UnitStore) -> None:
        store.upsert([unit(uid) for uid in PAUSED])
        for uid in PAUSED:
            pause_for_usage(store, uid, until)

    clock.advance((HOURS + 1) * 3600)

    lines = status_lines(tmp_path, monkeypatch, capsys, record=record)

    assert [line for line in lines if "paused for usage" in line] == []


def test_status_counts_the_paused_units_toward_the_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clock = fake_clock.install(monkeypatch)
    with_threads(monkeypatch, *PAUSED)

    lines = status_lines(
        tmp_path,
        monkeypatch,
        capsys,
        [unit("ready/1")],
        limit=len(PAUSED),
        record=pause_both(clock),
    )

    [full] = [line for line in lines if "queue is full" in line]
    assert f"{len(PAUSED)} units in progress, limit {len(PAUSED)}" in full


def test_explain_names_the_pause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clock = fake_clock.install(monkeypatch)
    with_threads(monkeypatch, *PAUSED)
    inst = make_installation(tmp_path, planning={"state_dir": "."})
    pause_both(clock)(UnitStore(inst.state_dir / "units.json"))
    run_status(inst, monkeypatch, capsys)

    assert cmd_explain(argparse.Namespace(unit=PAUSED[0], at=None), inst) == 0

    out = capsys.readouterr().out
    assert "paused for usage" in out
    # The time is read as the status reads it: local, as a clock time, not an ISO stamp.
    ends = (clock.now() + timedelta(hours=HOURS)).astimezone()
    assert f"until {ends:%H:%M}" in out
    assert ends.isoformat() not in out


def test_explain_does_not_name_a_pause_whose_time_has_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clock = fake_clock.install(monkeypatch)
    with_threads(monkeypatch, *PAUSED)
    inst = make_installation(tmp_path, planning={"state_dir": "."})
    pause_both(clock)(UnitStore(inst.state_dir / "units.json"))
    run_status(inst, monkeypatch, capsys)
    capsys.readouterr()
    clock.advance((HOURS + 1) * 3600)

    assert cmd_explain(argparse.Namespace(unit=PAUSED[0], at=None), inst) == 0

    assert "paused for usage" not in capsys.readouterr().out
