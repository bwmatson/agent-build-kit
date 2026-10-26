"""A working copy with a pipeline worktree and machine files to carry, built with real git."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.init.scaffold import template
from agent_build_kit.machine_files import Carried
from agent_build_kit.pipeline.planning_sync import write_pipeline_marker
from tests.factories import commit_files, git
from tests.planning_worktree_support import InRepo, working_copy_of

# The packaged `.gitignore`, which ignores every machine file.
GITIGNORE = template("gitignore")

CONTENT = {".env": "TOKEN=one\n", "abk.local.yaml": "planning: {}\n", "scrub.local": "secret\n"}


def machine_repo(base: Path, *, ignore: str = GITIGNORE) -> InRepo:
    """A working copy on `main` whose `.gitignore` is `ignore`, published to a bare origin, and a
    detached worktree of it recorded in the pipeline marker."""
    bare, working_copy = working_copy_of(base)
    commit_files(working_copy, "ignore", {".gitignore": ignore})
    git(working_copy, "push", "-q", "origin", "main")
    worktree = base / "planning"
    git(working_copy, "worktree", "add", "-q", "--detach", str(worktree), "HEAD")
    write_pipeline_marker(working_copy, worktree)
    return InRepo(origin=bare, working_copy=working_copy, worktree=worktree)


def give(working_copy: Path, *names: str) -> None:
    """Write these machine files into the working copy, each with its own content."""
    for name in names:
        (working_copy / name).write_text(CONTENT[name])


def results(carried: tuple[Carried, ...]) -> dict[str, str]:
    """What `carry` reported, name to result."""
    return {item.name: item.result for item in carried}
