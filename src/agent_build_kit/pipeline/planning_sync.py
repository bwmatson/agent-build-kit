"""The role of a planning root, the pipeline marker, and the one sync of the pipeline worktree."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen


class PlanningMode(StrEnum):
    SEPARATE = "separate"
    WORKING_COPY = "working copy"
    PIPELINE_WORKTREE = "pipeline worktree"


class SyncOutcome(StrEnum):
    SYNCED = "synced"
    CURRENT = "current"
    AHEAD = "ahead"
    STOPPED = "stopped"
    SKIPPED = "skipped"


class SyncResult(Frozen):
    outcome: SyncOutcome
    reason: str = ""


def planning_mode(inst: Installation) -> PlanningMode:
    raise NotImplementedError


def marker_path(root: Path) -> Path:
    raise NotImplementedError


def write_pipeline_marker(root: Path, worktree: Path) -> Path:
    raise NotImplementedError


def read_pipeline_marker(root: Path) -> Path | None:
    raise NotImplementedError


def remove_pipeline_marker(root: Path) -> None:
    raise NotImplementedError


def live_pipeline_worktree(inst: Installation) -> Path | None:
    raise NotImplementedError


def sync_planning(inst: Installation, say: Callable[[str], None]) -> SyncResult:
    raise NotImplementedError
