"""The files that make an installation this machine's, and carrying them into the pipeline
worktree."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.timers import PlanningWorktreeRefused

MACHINE_FILES: tuple[str, ...] = ()


class Carried(Frozen):
    """What `carry` did, or would do, for one machine file: `linked`, `unchanged`, `repointed`
    or `would link`."""

    name: str
    result: str


class MachineFileRefused(PlanningWorktreeRefused):
    """A machine file that cannot be carried; the message names it."""


def carry(source: Path, worktree: Path, *, dry_run: bool) -> tuple[Carried, ...]:
    """Link each machine file `source` has into `worktree`; refuse before changing anything."""
    raise NotImplementedError
