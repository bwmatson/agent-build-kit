"""Which checkout a track works in when the planning repo is also a code repo."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.tracks import runner
from tests.factories import git
from tests.planning_worktree_support import in_repo, installation_at


@pytest.mark.parametrize("configured", [".", "working-copy"])
def test_a_track_works_in_the_pipeline_worktree_whatever_the_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, configured: str
) -> None:
    setup = in_repo(tmp_path)
    git(setup.working_copy, "remote", "set-url", "origin", "https://github.com/example/app.git")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr(runner, "repo_reachable", lambda name, inst: True)
    path = Path(".") if configured == "." else setup.working_copy
    inst = installation_at(setup.worktree, path)

    projects = runner.eligible_projects(inst)

    assert [project.path for project in projects] == [setup.worktree.resolve()]
