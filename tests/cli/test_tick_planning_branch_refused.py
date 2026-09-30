"""A tick that cannot put the planning repo back on its default branch stops
before it reads any state."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from tests.conftest import make_installation
from tests.factories import git, init_repo


def test_a_tick_that_cannot_restore_the_default_branch_stops_before_reading_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = make_installation(tmp_path)
    init_repo(tmp_path)
    (tmp_path / "file").write_text("x")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "first")
    git(tmp_path, "checkout", "-q", "-b", "stray-branch")
    (tmp_path / "file").write_text("changed on the stray branch")
    git(tmp_path, "commit", "-q", "-am", "diverge")
    (tmp_path / "file").write_text("local change the checkout would overwrite")
    read: list[object] = []
    monkeypatch.setattr(cli, "store_for", lambda installation: read.append(installation))

    assert cli.cmd_tick(argparse.Namespace(dry_run=False), inst) != 0

    assert read == []
    assert git(tmp_path, "symbolic-ref", "--short", "HEAD") == "stray-branch"
