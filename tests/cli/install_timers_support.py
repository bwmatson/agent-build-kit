"""Helpers for the tests of `abk install-timers` from a planning repo that is also a code repo
(the `working_copy` fixture is in this folder's conftest)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_build_kit.init.scaffold import template
from tests.factories import commit_files, git
from tests.loginctl_fake import Loginctl
from tests.planning_worktree_support import add_pipeline_worktree


def planning_home_of(tmp_path: Path) -> Path:
    """The planning home of the `working_copy` fixture's installation."""
    return tmp_path / "home" / ".local" / "share" / "app" / "planning"


def worktree_of(tmp_path: Path) -> Path:
    return planning_home_of(tmp_path) / "worktree"


class Systemctl(Loginctl):
    """The manager's answers: every command succeeds, and `is-active` says so only for the units
    in `active`."""

    def __init__(self, *active: str) -> None:
        super().__init__("yes")
        self.active = set(active)

    def __call__(self, argv, **kwargs):
        if "is-active" in argv:
            super().__call__(argv, **kwargs)
            on = bool(self.active & set(argv))
            return subprocess.CompletedProcess(
                argv, 0 if on else 3, "active\n" if on else "inactive\n", ""
            )
        return super().__call__(argv, **kwargs)


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
    return add_pipeline_worktree(repo, worktree)


def add_legacy_worktree(repo: Path, tmp_path: Path) -> Path:
    """The pipeline worktree at the place earlier installs made it: the planning home itself."""
    legacy = planning_home_of(tmp_path)
    legacy.parent.mkdir(parents=True)
    return add_pipeline_worktree(repo, legacy)
