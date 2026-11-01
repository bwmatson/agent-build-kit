"""The board the kit wants, computed from the planning state alone (spec: tracker-push).

A pure computation: the items of each configured level with their titles, bodies, states,
markers and parents, from the change's files, the unit plan and the stored unit states. It
calls no tracker; the reconciler compares its answer with what was last synced.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.group_paths import line_paths
from agent_build_kit.pipeline.units import Unit, UnitState
from agent_build_kit.pipeline.work_graph import (
    TaskGroup,
    group_sections,
    read_tasks,
    validate_tasks,
)
from agent_build_kit.trackers.base import ItemKind
from agent_build_kit.trackers.config import TrackerSection

# The kit's state and tags for the state of the unit that covers a group.
_UNIT_STATES: dict[UnitState, tuple[str, tuple[str, ...]]] = {
    UnitState.PLANNED: ("new", ()),
    UnitState.RUNNING: ("active", ()),
    UnitState.IN_REVIEW: ("active", ("in-review",)),
    UnitState.MERGED: ("done", ()),
    UnitState.SETTLING: ("done", ()),
    UnitState.SATISFIED: ("done", ()),
    UnitState.FAILED: ("active", ("blocked",)),
    UnitState.HELD: ("active", ("blocked",)),
    UnitState.RETIRED: ("removed", ()),
    UnitState.CLOSED: ("removed", ()),
    UnitState.UNPLANNED: ("removed", ()),
}
_DESIGN_LINK = re.compile(r"docs/designs/[\w./-]*\.md(?:#[\w-]+)?")
_TEST_TASK = re.compile(r"\s*-\s+\[[ xX]\]\s+\d+\.\d+\s+Test\b")


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


def _section(text: str, heading: str) -> str:
    """The `## heading` section of a markdown text, heading included; empty when absent."""
    kept: list[str] = []
    inside = False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = line[3:].strip() == heading
        if inside:
            kept.append(line)
    return "\n".join(kept).strip()


def _read(path: Path) -> str:
    return path.read_text() if path.is_file() else ""


def _change_title(name: str, folder: Path) -> str:
    for file in ("tasks.md", "proposal.md"):
        for line in _read(folder / file).splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    return name


def _change_body(folder: Path, name: str, repo_url: str) -> str:
    proposal = _read(folder / "proposal.md")
    design = _section(_read(folder / "design.md"), "Decisions")
    parts = [_section(proposal, "Why"), _section(proposal, "What Changes"), design]
    for spec in sorted((folder / "specs").glob("*/spec.md")):
        text = _read(spec)
        start = text.find("### Requirement")
        if start >= 0:
            parts.append(text[start:].strip())
    links = [f"Change folder: {repo_url}/openspec/changes/{name}"]
    links += [f"Design: {repo_url}/{found}" for found in _DESIGN_LINK.findall(design)]
    return "\n\n".join([*(part for part in parts if part), *links])


def _group_body(section: str, group: TaskGroup) -> str:
    checklist = section.split("\n", 1)[1].strip() if "\n" in section else ""
    tests = dict.fromkeys(
        path
        for line in checklist.splitlines()
        if _TEST_TASK.match(line)
        for path in line_paths(line)
    )
    parts = [f"Tier: {group.tier}", checklist]
    if tests:
        parts.insert(1, "Tests: " + ", ".join(tests))
    return "\n\n".join(parts)


def _group_state(change: str, number: int, units: Sequence[Unit]) -> tuple[str, tuple[str, ...]]:
    covering = [
        unit
        for unit in units
        if not unit.superseded_by
        and any(member.change == change and number in member.groups for member in unit.members())
    ]
    return _UNIT_STATES[covering[-1].state] if covering else ("new", ())


def _change_state(states: Sequence[str]) -> str:
    if states and all(state == "done" for state in states):
        return "done"
    return "new" if all(state == "new" for state in states) else "active"


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
    epics = epics or {}
    per_level: dict[str, list[WantedItem]] = {level: [] for level in section.levels}
    for name in changes:
        folder = changes_dir / name
        tasks_file = folder / "tasks.md"
        groups, _ = validate_tasks(tasks_file)
        text = tasks_file.read_text()
        states = {group.number: _group_state(name, group.number, units) for group in groups}

        def markers(group: int = 0, task: int = 0, name: str = name) -> dict[str, str]:
            return {"change": name, "group": f"{name}:{group}", "task": f"{name}:{group}.{task}"}

        def parent(level: str, group: int = 0, name: str = name) -> tuple[str | None, str | None]:
            """The marker of the wanted parent and the recorded id of the epic."""
            above = section.parent_level(level)
            if above == "epic":
                return None, epics.get(name)
            return (markers(group)[above] if above else None), None

        if "change" in per_level:
            marker_of, epic_id = parent("change")
            per_level["change"].append(
                WantedItem(
                    level="change",
                    marker=name,
                    title=_change_title(name, folder),
                    body=_change_body(folder, name, repo_url),
                    state=_change_state([state for state, _ in states.values()]),
                    parent_marker=marker_of,
                    parent_id=epic_id,
                )
            )
        if "group" in per_level:
            for group in groups:
                state, tags = states[group.number]
                (section_text,) = group_sections(text, [group.number])
                marker_of, epic_id = parent("group", group.number)
                per_level["group"].append(
                    WantedItem(
                        level="group",
                        marker=markers(group.number)["group"],
                        title=group.title,
                        body=_group_body(section_text, group),
                        state=state,
                        tags=tags,
                        parent_marker=marker_of,
                        parent_id=epic_id,
                    )
                )
        if "task" in per_level:
            for task in read_tasks(tasks_file, name):
                marker_of, epic_id = parent("task", task.group)
                per_level["task"].append(
                    WantedItem(
                        level="task",
                        marker=task.key,
                        title=task.text.splitlines()[0],
                        body=task.text,
                        state="done" if task.done else "new",
                        parent_marker=marker_of,
                        parent_id=epic_id,
                    )
                )
    return tuple(item for items in per_level.values() for item in items)
