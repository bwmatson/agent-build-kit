"""The files that make an installation this machine's, and carrying them into the pipeline
worktree."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.config import OVERLAY_FILENAME
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.planning_repo import PlanningWorktreeRefused
from agent_build_kit.pipeline.shell import is_ignored, is_tracked
from agent_build_kit.scrub_terms import LOCAL_LIST

MACHINE_FILES: tuple[str, ...] = (".env", OVERLAY_FILENAME, LOCAL_LIST)
# The machine files that belong to a configuration: the ones `.gitignore` must hold on a
# migration and the doctor checks are not committed.
CONFIG_LOCAL_FILES = tuple(name for name in MACHINE_FILES if name != ".env")

LINKED = "linked"
UNCHANGED = "unchanged"
REPOINTED = "repointed"
WOULD_LINK = "would link"


class Carried(Frozen):
    """What `carry` did, or would do, for one machine file: `linked`, `unchanged`, `repointed`
    or `would link`."""

    name: str
    result: str


class MachineFileRefused(PlanningWorktreeRefused):
    """A machine file that cannot be carried; the message names it."""


def _classify(name: str, source: Path, worktree: Path) -> str:
    """What carrying `name` does, or raises `MachineFileRefused` when it must not."""
    path = worktree / name
    if is_tracked(worktree, name):
        raise MachineFileRefused(
            f"{path} is tracked by git, which would commit a machine file; "
            f"`git rm --cached {name}` in {worktree}, then install again"
        )
    if not is_ignored(worktree, name):
        raise MachineFileRefused(
            f"{path} is not ignored by git; add `{name}` to .gitignore, then install again"
        )
    if path.is_symlink():
        if not path.exists():
            return REPOINTED
        if path.resolve() == source.resolve():
            return UNCHANGED
        raise MachineFileRefused(f"{path} is a link to {path.resolve()}, not to {source}")
    if path.exists():
        if path.read_bytes() == source.read_bytes():
            return UNCHANGED
        raise MachineFileRefused(
            f"{path} is a different file from {source}; move it away, then install again"
        )
    return LINKED


def carry(source: Path, worktree: Path, *, dry_run: bool) -> tuple[Carried, ...]:
    """Link each machine file `source` has into `worktree`; refuse before changing anything."""
    plan = [
        (name, _classify(name, source / name, worktree))
        for name in MACHINE_FILES
        if (source / name).exists()
    ]
    carried = []
    for name, result in plan:
        if result in (LINKED, REPOINTED):
            if not dry_run:
                path = worktree / name
                path.unlink(missing_ok=True)
                path.symlink_to((source / name).absolute())
            if dry_run:
                result = WOULD_LINK
        carried.append(Carried(name=name, result=result))
    return tuple(carried)
