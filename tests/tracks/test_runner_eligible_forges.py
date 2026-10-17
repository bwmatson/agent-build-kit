"""Which repos a track works on, by the forge each one is on and what its `origin` names."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.tracks import runner
from tests.conftest import make_installation
from tests.factories import git
from tests.planning_worktree_support import working_copy_of

GITHUB_SHAPED = "git@github.com:example/app.git"


def eligible(tmp_path: Path, forge: str, origin: str | None) -> list[runner.Project]:
    _, app = working_copy_of(tmp_path)
    if origin is not None:
        git(app, "remote", "set-url", "origin", origin)
    inst = make_installation(
        tmp_path / "planning",
        repos={"app": {"path": str(app), "slug": "example/app", "forge": forge}},
    )
    return runner.eligible_projects(inst)


def test_a_local_forge_repo_with_a_bare_local_path_origin_is_eligible(tmp_path: Path) -> None:
    assert [p.name for p in eligible(tmp_path, "local", None)] == ["app"]


def test_a_local_forge_repo_with_a_host_shaped_origin_is_eligible(tmp_path: Path) -> None:
    assert [p.name for p in eligible(tmp_path, "local", GITHUB_SHAPED)] == ["app"]


def test_a_github_repo_whose_origin_no_forge_recognises_is_skipped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert eligible(tmp_path, "github", None) == []
    assert "no forge recognises origin" in capsys.readouterr().out
