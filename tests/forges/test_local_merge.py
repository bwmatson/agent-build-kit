"""The local forge does not merge: a merge there is a person's, made with git."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.forges.base import MergeRefused
from agent_build_kit.forges.local import LocalForge
from tests.conftest import make_installation
from tests.factories import git, init_repo

HEAD = "spec/feature/2"


def test_the_local_forge_does_not_merge_and_refuses_a_merge_as_a_persons(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "app")
    (repo / "base.txt").write_text("x\n")
    git(repo, "add", "base.txt")
    git(repo, "commit", "-q", "-m", "base")
    git(repo, "checkout", "-q", "-b", HEAD)
    (repo / "a.txt").write_text("a\n")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", "add a")
    git(repo, "checkout", "-q", "main")
    installation = make_installation(
        tmp_path / "planning", repos={"app": {"path": str(repo), "forge": "local"}}
    )
    forge = LocalForge(installation.state_dir)
    repo_id = forge.identity(installation.repo("app"))
    number = forge.create_pr(repo_id, head=HEAD, base="main", title="Feature", body="Body")
    tip = git(repo, "rev-parse", HEAD)
    trunk = git(repo, "rev-parse", "main")
    assert forge.merges is False
    before = git(repo, "status", "--porcelain")

    with pytest.raises(MergeRefused) as refused:
        forge.merge_pr(repo_id, number, head=tip)

    assert "person" in refused.value.reason
    assert git(repo, "rev-parse", "main") == trunk
    assert git(repo, "rev-parse", HEAD) == tip
    assert git(repo, "status", "--porcelain") == before
    assert [p.state for p in forge.list_prs(repo_id)] == ["open"]
