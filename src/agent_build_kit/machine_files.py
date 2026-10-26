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
    """What carrying `name` does, or raises `MachineFileRefused` when it must not. The repairs a
    refusal names are made in the working copy and published: the worktree is moved to the
    default branch's tip, and an edit made in it stops that."""
    path = worktree / name
    working_copy = source.parent
    if is_tracked(worktree, name):
        raise MachineFileRefused(
            f"{path} is tracked by git, which would commit a machine file; run "
            f"`git rm --cached {name}` in {working_copy}, commit and push it to the default "
            "branch, then install again"
        )
    if not is_ignored(worktree, name):
        raise MachineFileRefused(
            f"{path} is not ignored by git; add `{name}` to .gitignore in {working_copy}, "
            "commit and push it to the default branch, then install again"
        )
    if path.is_symlink():
        if not path.exists():
            return REPOINTED
        if path.resolve() == source.resolve():
            return UNCHANGED
        raise MachineFileRefused(f"{path} is a link to {path.resolve()}, not to {source}")
    if path.exists():
        if path.is_file() and path.read_bytes() == source.read_bytes():
            return UNCHANGED
        raise MachineFileRefused(
            f"{path} is not a copy of {source}; move it away, then install again"
        )
    return LINKED


def carry(source: Path, worktree: Path, *, dry_run: bool) -> tuple[Carried, ...]:
    """Link each machine file `source` has into `worktree`; refuse before changing anything. A
    dry run over a worktree that is not made yet says `would link` for each file, with no git
    check to make."""
    present = [name for name in MACHINE_FILES if (source / name).exists()]
    if dry_run and not worktree.is_dir():
        return tuple(Carried(name=name, result=WOULD_LINK) for name in present)
    plan = [(name, _classify(name, source / name, worktree)) for name in present]
    carried = []
    for name, result in plan:
        if result in (LINKED, REPOINTED):
            if dry_run:
                result = WOULD_LINK
            else:
                path = worktree / name
                path.unlink(missing_ok=True)
                path.symlink_to((source / name).absolute())
        carried.append(Carried(name=name, result=result))
    return tuple(carried)
