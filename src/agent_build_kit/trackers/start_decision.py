"""Whether a unit may start, given who owns the board items it covers (spec: unit-claim)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from agent_build_kit import config, trackers
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.tracker_file import TrackerFile, mapping_target, read_for_target
from agent_build_kit.pipeline.units import Unit, in_progress
from agent_build_kit.trackers.config import section_for
from agent_build_kit.trackers.levels import group_key, task_group_key

NO_BOARD_ITEM = "no board item yet"


class StartDecision(Frozen):
    """The answer for one unit: start it, skip it (someone else owns it) or wait (the board is
    not ready). `items` holds the ids of the board items the reason is about."""

    outcome: Literal["start", "skip", "wait"]
    reason: str = ""
    items: tuple[str, ...] = ()
    claimed: tuple[str, ...] = ()


def _covered_ids(
    levels: Sequence[str], tracker_file: TrackerFile | None, change: str, groups: Sequence[int]
) -> list[str] | None:
    """The ids of the items the groups cover at the levels checked, None when one has no item
    yet. The change item is checked only when it is the lowest level in use. A group whose task
    items are only partly mirrored does not wait: the items there are checked."""
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
    `changes_dir`; a repo with no tracker section starts it and makes no call. A failure to read
    the section, the tracker file or the board is a wait naming it, never a raise: the unit is
    not started without knowing who owns it, and no other unit is touched."""
    if unit.repo not in config.active().repos:
        return StartDecision(outcome="start")  # a repo the configuration lacks has no tracker
    try:
        return _decide(unit, changes_dir)
    except Exception as error:  # noqa: BLE001
        return StartDecision(outcome="wait", reason=f"tracker unavailable: {error}")


def _decide(unit: Unit, changes_dir: Path) -> StartDecision:
    section = section_for(unit.repo)
    if section is None:
        return StartDecision(outcome="start")
    tracker = trackers.for_repo(unit.repo)
    if tracker is None:
        return StartDecision(outcome="start")
    wanted: list[str] = []
    for member in unit.members():
        found = read_for_target(changes_dir / member.change, section.kind, mapping_target(section))
        ids = _covered_ids(section.levels, found, member.change, member.groups)
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


def start_gate(unit: Unit, graph: Sequence[Unit], *, changes_dir: Path) -> StartDecision:
    """The one rule the round applies: a unit already in progress is the kit's and is not asked;
    any other is decided by `start_decision`."""
    if in_progress(unit, graph):
        return StartDecision(outcome="start")
    return start_decision(unit, changes_dir=changes_dir)
