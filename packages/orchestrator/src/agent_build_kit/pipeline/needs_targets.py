"""Where each `Needs:` line of the active changes leads, and which of them are unmet."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import StoredUnit


class UnmetNeed(Frozen):
    """One `Needs:` line whose target group is not covered by a unit and not archived."""

    change: str
    group: int
    line: int
    target: str
    target_group: int
    outcome: str
    wording: str


def unmet_needs(
    tasks_files: Sequence[Path],
    units: Sequence[StoredUnit],
    changes_dir: Path,
    outlines: Collection[str],
    plan_states: Mapping[str, str],
) -> list[UnmetNeed]:
    """Each unmet `Needs:` line of `tasks_files`, with its outcome: `not_planned`, `no_group`,
    `no_tasks`, `outline` or `missing`."""
    raise NotImplementedError
