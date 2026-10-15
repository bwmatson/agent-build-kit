"""A repository that is also the planning root: its bare origin, the person's working copy and
the pipeline worktree, built with real git."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.planning_sync import write_pipeline_marker
from tests.conftest import make_installation
from tests.factories import commit_files, git, init_repo


class InRepo(Frozen):
    origin: Path | None
    working_copy: Path
    worktree: Path


def in_repo(base: Path, *, origin: bool = True) -> InRepo:
    """A working copy of `app` on `main` holding `runs/units.json`, published to a bare origin
    (unless `origin` is False), and a detached worktree of it at that commit, recorded in the
    pipeline marker."""
    working_copy = init_repo(base / "app")
    commit_files(working_copy, "start", {"runs/units.json": "[]\n", "README.md": "app\n"})
    bare = None
    if origin:
        bare = base / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
        git(working_copy, "remote", "add", "origin", str(bare))
        git(working_copy, "push", "-q", "origin", "main")
        git(working_copy, "remote", "set-head", "origin", "main")
    worktree = base / "planning"
    git(working_copy, "worktree", "add", "-q", "--detach", str(worktree), "HEAD")
    write_pipeline_marker(working_copy, worktree)
    return InRepo(origin=bare, working_copy=working_copy, worktree=worktree)


def installation_at(root: Path, repo_path: Path, **overrides) -> Installation:
    """An installation whose root is `root` and whose one repo, `app`, is at `repo_path`."""
    repos = {"app": {"path": str(repo_path), "slug": "example/app"}}
    return make_installation(root, repos=repos, **overrides)


def publish_elsewhere(setup: InRepo, files: dict[str, str], message: str = "elsewhere") -> str:
    """Commit these files to `main` on the origin through another clone; the new tip."""
    assert setup.origin is not None
    clone = setup.origin.parent / f"clone-{len(list(setup.origin.parent.glob('clone-*')))}"
    subprocess.run(["git", "clone", "-q", str(setup.origin), str(clone)], check=True)
    git(clone, "config", "user.email", "t@t.t")
    git(clone, "config", "user.name", "t")
    commit_files(clone, message, files)
    git(clone, "push", "-q", "origin", "main")
    return git(clone, "rev-parse", "HEAD")
