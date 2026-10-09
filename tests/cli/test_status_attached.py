"""`abk status` lists the units a chat is attached to with the number of changed files, and
says what to do about one whose server has gone."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.attach_driver import leave_lease
from tests.conftest import make_installation
from tests.factories import stored_unit


def status_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> list[str]:
    workspace = make_installation(
        tmp_path, planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees"))
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [stored_unit(f"one/{n}", change="one") for n in (1, 2, 3)]
        + [stored_unit("two/1", change="two")]
    )
    live = Leases(lease_dir(tmp_path))
    live.take("one/1", "tab:a", checkouts=("worktree",))
    live.mark_changes("one/1", "tab:a", 3)
    leave_lease(lease_dir(tmp_path), "one/2", files=1)
    leave_lease(lease_dir(tmp_path), "one/3")  # holds nothing
    monkeypatch.setattr(cli, "current_usage", lambda: None)

    assert cli.cmd_status(argparse.Namespace(), workspace) == 0

    return capsys.readouterr().out.splitlines()


def test_status_lists_an_attached_unit_with_the_number_of_changed_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status_lines(tmp_path, monkeypatch, capsys)

    live = next(line for line in lines if "one/1" in line)
    assert "attached" in live
    assert "3 files" in live


def test_status_says_to_start_the_server_or_release_when_the_server_has_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status_lines(tmp_path, monkeypatch, capsys)

    stale = next(line for line in lines if "one/2" in line)
    assert "attached" in stale
    assert "1 file" in stale
    assert "abk attach release" in stale
    assert "server" in stale


def test_status_lists_no_unit_that_nothing_is_attached_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status_lines(tmp_path, monkeypatch, capsys)

    assert not any("attached" in line and "one/3" in line for line in lines)
    assert not any("attached" in line and "two/1" in line for line in lines)
