"""Naming the piece in a picked commit rewrites only its message, without the repo's commit
hooks, which already passed it on the superseded branch (spec: split-planning)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.commit_order import cherry_pick
from agent_build_kit.pipeline.shell import git, git_out
from tests.factories import init_repo


def test_a_failing_pre_commit_hook_does_not_stop_the_unit_trailer_rewrite(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / "base.txt").write_text("base\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "start")
    git(repo, "checkout", "-q", "-b", "old")
    (repo / "work.txt").write_text("work\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "test: G1\n\nUnit: app/1\n")
    old = git_out(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    git(repo, "checkout", "-q", "-b", "piece")
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)

    picked = cherry_pick(repo, [old], unit_id="app/1-s1")

    assert picked is True
    assert "Unit: app/1-s1" in git_out(repo, "log", "-1", "--format=%B").splitlines()
    assert git(repo, "status", "--porcelain").stdout.strip() == ""
