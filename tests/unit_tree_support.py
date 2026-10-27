"""A unit's worktree as git knows it: the pipeline finds a unit's worktree through
`git worktree list`, so a test that needs one registers a real one."""

from __future__ import annotations

from pathlib import Path

from tests.factories import commit_files, git, init_repo


def registered_tree(repo: Path, branch: str, path: Path) -> Path:
    """`branch` checked out at `path` by `git worktree add`, `repo` made a repository with one
    commit when it is not one yet. A tree already there is returned as it is."""
    if (path / ".git").exists():
        return path
    if not (repo / ".git").exists():
        init_repo(repo)
        commit_files(repo, "start", {"README.md": "start\n"})
    path.parent.mkdir(parents=True, exist_ok=True)
    if git(repo, "branch", "--list", branch).strip():
        git(repo, "worktree", "add", "-q", str(path), branch)
    else:
        git(repo, "worktree", "add", "-q", "-b", branch, str(path), "HEAD")
    return path
