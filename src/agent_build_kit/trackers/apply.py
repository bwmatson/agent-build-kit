"""Applies what people changed on a repo's board to the pipeline (spec: tracker-pull)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.trackers.base import Change


class ApplyConflict(Frozen):
    """A disagreement the apply step left for a person: the item, what it was about, both
    values and a note saying why."""

    item_id: str
    field: str
    spec_value: str = ""
    tracker_value: str = ""
    note: str = ""


class Applied(Frozen):
    """What an apply did not act on but kept a record of, and the conflicts it opened."""

    recorded: tuple[str, ...] = ()
    conflicts: tuple[ApplyConflict, ...] = ()


def apply_changes(
    repo: str,
    changes: Sequence[Change],
    *,
    changes_dir: Path,
    state_dir: Path,
    store: UnitStore,
    log: Callable[[str], None] = print,
) -> Applied:
    """Hold or release units, tick or untick boxes, rewrite task lines and append tasks for the
    board changes `changes` of `repo`, writing the planning files only through the pipeline."""
    raise NotImplementedError
