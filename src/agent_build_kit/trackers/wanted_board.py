"""The board the kit wants, computed from the planning state alone (spec: tracker-push).

A pure computation: the items of each configured level with their titles, bodies, states,
markers and parents, from the change's files, the unit plan and the stored unit states. It
calls no tracker; the reconciler compares its answer with what was last synced.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.units import Unit
from agent_build_kit.trackers.base import ItemKind
from agent_build_kit.trackers.config import TrackerSection


class WantedItem(Frozen):
    """One item the board should hold. `parent_marker` names the wanted item it hangs under;
    `parent_id` is the recorded id of the manual epic, which is never a wanted item."""

    level: ItemKind
    marker: str
    title: str
    body: str
    # The kit's state: `new`, `active`, `done` or `removed`.
    state: str
    # `in-review` or `blocked`, from the unit state.
    tags: tuple[str, ...] = ()
    parent_marker: str | None = None
    parent_id: str | None = None


def wanted_board(
    section: TrackerSection,
    changes_dir: Path,
    changes: Sequence[str],
    units: Sequence[Unit],
    *,
    repo_url: str,
    epics: Mapping[str, str] | None = None,
) -> tuple[WantedItem, ...]:
    """The items wanted for `changes` (folders of `changes_dir`) on the levels of `section`,
    outermost level first. `repo_url` is where the planning repo's files are browsed, and
    `epics` maps a change to the epic id its tracker file records."""
    raise NotImplementedError
