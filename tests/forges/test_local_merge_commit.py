"""The local forge cannot say which commit a merge produced: it answers empty
(spec: review-outcomes)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.forges.local import LocalForge
from tests.conftest import make_installation
from tests.factories import git, init_repo

HEAD = "spec/feature/2"


def test_the_local_forge_answers_empty_for_every_pull_request(tmp_path: Path) -> None:
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
    open_pr = forge.create_pr(repo_id, head=HEAD, base="main", title="Feature", body="Body")
    closed_pr = forge.create_pr(repo_id, head=HEAD, base="main", title="Other", body="Body")
    forge.close_pr(repo_id, closed_pr)
    git(repo, "merge", "-q", "--no-ff", HEAD, "-m", "merge by a person")

    assert forge.merge_commit(repo_id, open_pr) is None
    assert forge.merge_commit(repo_id, closed_pr) is None
    assert forge.merge_commit(repo_id, 999) is None
