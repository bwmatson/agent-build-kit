from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import timers
from agent_build_kit.config import dump
from tests.loginctl_fake import Loginctl, SubprocessModule
from tests.planning_worktree_support import installation_at, working_copy_of


@pytest.fixture
def working_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A working copy that is its own planning root, on a machine with its own home and units."""
    _, repo = working_copy_of(tmp_path / "repos")
    (repo / "abk.yaml").write_text(dump(installation_at(repo, repo).config))
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(timers, "user_unit_dir", lambda: tmp_path / "units")
    monkeypatch.setattr(timers, "subprocess", SubprocessModule(Loginctl("yes")))
    monkeypatch.chdir(repo)
    return repo
