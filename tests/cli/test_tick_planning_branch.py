"""A tick starts on the planning repo's default branch: state is read and
written there, and a branch nobody chose is not a place to do either."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.conftest import make_installation
from tests.factories import git, init_repo


def test_a_tick_on_another_branch_restores_the_default_branch_before_reading_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = make_installation(tmp_path)
    init_repo(tmp_path)
    (tmp_path / "file").write_text("x")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "first")
    git(tmp_path, "checkout", "-q", "-b", "stray-branch")
    read_on: list[str] = []

    def store_for(installation) -> UnitStore:
        read_on.append(git(tmp_path, "symbolic-ref", "--short", "HEAD"))
        return UnitStore(tmp_path / "units.json")

    monkeypatch.setattr(cli, "store_for", store_for)

    assert cli.cmd_tick(argparse.Namespace(dry_run=False), inst) == 0

    assert read_on and set(read_on) == {"main"}
    assert git(tmp_path, "symbolic-ref", "--short", "HEAD") == "main"
    assert "stray-branch" in capsys.readouterr().out
