"""`abk status` names the unit holding the tier 2 lock and for how long
(spec: unit-scheduling, "The status shows who holds the tier 2 lock")."""

from __future__ import annotations

import argparse
import fcntl
import os
import re
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import e2e
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.fake_clock import install
from tests.tier2_lock_fakes import Foreign, dead_pid, record_line

FORTY_MINUTES = 40 * 60


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    installation = make_installation(
        tmp_path, planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees"))
    )
    UnitStore(tmp_path / "units.json").upsert([stored_unit("one/1", change="one")])
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    install(monkeypatch)
    return installation


def tier2_lines(workspace: Installation, capsys: pytest.CaptureFixture[str]) -> list[str]:
    assert cli.cmd_status(argparse.Namespace(), workspace) == 0
    unstamped = [re.sub(r"^\[[^\]]*\] ", "", line) for line in capsys.readouterr().out.splitlines()]
    return [line for line in unstamped if line.startswith("e2e-test")]


def test_status_names_the_holder_and_how_long_it_has_held_the_lock(
    workspace: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    holder = Foreign(
        workspace.state_dir / "tier2.lock", "other/1", pid=os.getpid(), age=FORTY_MINUTES
    )
    try:
        lines = tier2_lines(workspace, capsys)
    finally:
        holder.release()

    assert len(lines) == 1
    assert lines[0].startswith("e2e-test: held by other/1 for 40m")


def test_status_shows_a_stale_record_of_a_free_lock_as_stale_and_leaves_the_file(
    workspace: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    lock = workspace.state_dir / "tier2.lock"
    lock.write_text(record_line("other/1", dead_pid(), FORTY_MINUTES))
    before = lock.read_text()

    lines = tier2_lines(workspace, capsys)

    assert len(lines) == 1
    assert "stale" in lines[0] and "other/1" in lines[0]
    assert "held by" not in lines[0]
    assert lock.read_text() == before


def test_status_shows_no_tier_2_line_once_the_lock_is_free_and_empty(
    workspace: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    lock = workspace.state_dir / "tier2.lock"
    holder = Foreign(lock, "other/1", pid=os.getpid())
    try:
        assert tier2_lines(workspace, capsys), "held: a line"
    finally:
        holder.release()
    lock.write_text("")
    assert tier2_lines(workspace, capsys) == [], "free and empty"

    lock.unlink()
    assert tier2_lines(workspace, capsys) == [], "no file"


def test_status_says_a_held_locks_recorded_process_is_gone(
    workspace: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    holder = Foreign(workspace.state_dir / "tier2.lock", "other/1", pid=dead_pid())
    try:
        lines = tier2_lines(workspace, capsys)
    finally:
        holder.release()

    assert len(lines) == 1
    assert "held" in lines[0] and "other/1" in lines[0]
    assert "gone" in lines[0]
    assert "stale" not in lines[0]


def test_status_says_a_held_lock_with_no_record_yet_is_held(
    workspace: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    lock = workspace.state_dir / "tier2.lock"
    lock.write_text("")
    with lock.open("r+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        lines = tier2_lines(workspace, capsys)

    assert len(lines) == 1
    assert "held" in lines[0]


def test_reading_the_status_leaves_the_lock_free_for_the_next_holder(
    workspace: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    lock = workspace.state_dir / "tier2.lock"
    lock.write_text(record_line("other/1", dead_pid()))

    assert tier2_lines(workspace, capsys), "the status read the lock"

    with e2e.stack_lock(lock, timeout=0.0, holder="two/1"):
        record = e2e.read_lock_record(lock.read_text())
    assert record is not None and record.unit == "two/1"
