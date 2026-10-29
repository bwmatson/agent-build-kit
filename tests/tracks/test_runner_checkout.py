"""A track works on a checkout: the git working-tree root of the path, not a `.git` entry."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.tracks import runner
from tests.tracks.test_runner import described_installation


def test_a_folder_with_a_git_entry_that_is_not_a_repository_is_not_a_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = described_installation(tmp_path / "planning")
    path = inst.repo("app").path
    (path / ".git").mkdir(parents=True)
    monkeypatch.setattr(runner, "repo_reachable", lambda name, inst: True)

    projects = runner.eligible_projects(inst, only="app")

    assert projects == []
    assert "skip app" in capsys.readouterr().out
