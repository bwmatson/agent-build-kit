"""Whether a unit may start, given who owns the board items it covers (spec: unit-claim)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal

from agent_build_kit import trackers
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.tracker_file import TrackerFile, read_tracker
from agent_build_kit.pipeline.units import HELD, PLANNED, Unit
from agent_build_kit.trackers.config import section_for
from agent_build_kit.trackers.levels import group_key, task_group_key

NO_BOARD_ITEM = "no board item yet"


class StartDecision(Frozen):
    """The answer for one unit: start it, skip it (someone else owns it) or wait (the board is
    not ready). `items` holds the ids of the board items the reason is about."""

    outcome: Literal["start", "skip", "wait"]
    reason: str = ""
    items: tuple[str, ...] = ()


def _covered_ids(
    levels: Sequence[str], tracker_file: TrackerFile | None, change: str, groups: Sequence[int]
) -> list[str] | None:
    """The ids of the items the groups cover at the levels checked, None when one has no item
    yet. The change item is checked only when it is the lowest level in use."""
    if tracker_file is None:
        return None
    if levels[-1] == "change":
        return [tracker_file.change.id] if tracker_file.change else None
    ids: list[str] = []
    for group in groups:
        key = group_key(change, group)
        if "group" in levels:
            if key not in tracker_file.groups:
                return None
            ids.append(tracker_file.groups[key].id)
        tasks = [
            entry.id for task, entry in tracker_file.tasks.items() if task_group_key(task) == key
        ]
        if "task" in levels:
            if "group" not in levels and not tasks:
                return None
            ids.extend(tasks)
    return ids


def start_decision(unit: Unit, *, changes_dir: Path) -> StartDecision:
    """The decision for `unit` against the tracker of its repo, whose tracker files are under
    `changes_dir`; a repo with no tracker section starts it and makes no call."""
    section = section_for(unit.repo)
    if section is None:
        return StartDecision(outcome="start")
    tracker = trackers.for_repo(unit.repo)
    if tracker is None:
        return StartDecision(outcome="start")
    wanted: list[str] = []
    for member in unit.members():
        ids = _covered_ids(
            section.levels, read_tracker(changes_dir / member.change), member.change, member.groups
        )
        if ids is None:
            return StartDecision(outcome="wait", reason=NO_BOARD_ITEM)
        wanted.extend(ids)
    sync = tracker.identity().name
    taken: list[str] = []
    people: list[str] = []
    for item_id in wanted:
        others = [who for who in tracker.get(item_id).assignees if who != sync]
        if others:
            taken.append(item_id)
            people.extend(who for who in others if who not in people)
    if taken:
        return StartDecision(
            outcome="skip", reason=f"assigned to {', '.join(people)}", items=tuple(taken)
        )
    return StartDecision(outcome="start", items=tuple(wanted))


def start_view(graph: Sequence[Unit], decide: Callable[[Unit], StartDecision]) -> list[Unit]:
    """`graph` with each planned unit `decide` does not start shown as held, so it takes no
    slot and the next ready unit is considered."""
    return [
        unit.model_copy(update={"state": HELD})
        if unit.state == PLANNED and decide(unit).outcome != "start"
        else unit
        for unit in graph
    ]
