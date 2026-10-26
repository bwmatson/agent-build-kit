"""Helpers for the tests of `abk install-timers` from a planning repo that is also a code repo
(the `working_copy` fixture is in this folder's conftest)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.init.scaffold import template
from agent_build_kit.pipeline.planning_sync import write_pipeline_marker
from tests.factories import commit_files, git


def worktree_of(tmp_path: Path) -> Path:
    return tmp_path / "home" / ".local" / "share" / "app" / "planning"


def publish_planning(repo: Path) -> None:
    """Commit the working copy's `abk.yaml` and the packaged `.gitignore` and publish them, so the
    worktree the install makes holds the configuration and ignores the machine files."""
    commit_files(
        repo,
        "planning",
        {".gitignore": template("gitignore"), "abk.yaml": (repo / "abk.yaml").read_text()},
    )
    git(repo, "push", "-q", "origin", "main")


def add_worktree(repo: Path, tmp_path: Path) -> Path:
    """The pipeline worktree at the place the install would make it, added by hand."""
    worktree = worktree_of(tmp_path)
    worktree.parent.mkdir(parents=True)
    git(repo, "worktree", "add", "-q", "--detach", str(worktree), "HEAD")
    write_pipeline_marker(repo, worktree)
    return worktree
