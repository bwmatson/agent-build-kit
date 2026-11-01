"""The board the kit wants, computed from the planning state alone (spec: tracker-push).

A pure computation: the items of each configured level with their titles, bodies, states,
markers and parents, from the change's files, the unit plan and the stored unit states. It
calls no tracker; the reconciler compares its answer with what was last synced.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Mapping, Sequence
from pathlib import Path

from agent_build_kit.config import active
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.group_paths import named_test_paths
from agent_build_kit.pipeline.pr_body import section_text
from agent_build_kit.pipeline.task_progress import TASKS_FILE
from agent_build_kit.pipeline.units import Unit, UnitState, carried_pairs
from agent_build_kit.pipeline.work_graph import TaskGroup, read_tasks, validate_tasks
from agent_build_kit.trackers.base import ItemKind
from agent_build_kit.trackers.config import TrackerSection
from agent_build_kit.trackers.folders import change_folder

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
# Which of several unfinished units shows on a group's item: the one doing work, then the
# ones stopped, then the ones waiting; the last is the strongest.
_UNFINISHED_ORDER = (
    UnitState.PLANNED,
    UnitState.IN_REVIEW,
    UnitState.FAILED,
    UnitState.HELD,
    UnitState.RUNNING,
)
# A repo-relative path of a document with a folder, and its optional anchor.
_DOCUMENT_LINK = re.compile(r"(?<![\w:/.-])[\w.-]+(?:/[\w.-]+)+\.md(?:#[\w-]+)?")


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


def _read(path: Path) -> str:
    return path.read_text() if path.is_file() else ""


def _headed(text: str, heading: str) -> str:
    """The section of `text` under `## heading`, with its heading; empty when it has none."""
    body = section_text(text, heading)
    return f"## {heading}\n\n{body}" if body else ""


def _change_title(name: str, folder: Path) -> str:
    for file in (TASKS_FILE, "proposal.md"):
        for line in _read(folder / file).splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    return name


def _link(label: str, browse: Callable[[str], str], path: str) -> list[str]:
    """The line `label: <address>`, none when the host gives no address for `path`. A `#anchor`
    on the path goes after the address."""
    where, hash_, anchor = path.partition("#")
    address = browse(where)
    return [f"{label}: {address}{hash_}{anchor}"] if address else []


def _change_body(folder: Path, changes_dir: Path, browse: Callable[[str], str]) -> str:
    proposal = _read(folder / "proposal.md")
    decisions = _headed(_read(folder / "design.md"), "Decisions")
    parts = [_headed(proposal, "Why"), _headed(proposal, "What Changes"), decisions]
    for spec in sorted((folder / "specs").glob("*/spec.md")):
        text = _read(spec)
        start = text.find("### Requirement")
        if start >= 0:
            parts.append(text[start:].strip())
    specs_dir = active().planning.specs_dir.strip("/")
    where = folder.relative_to(changes_dir).as_posix()
    links = _link("Change folder", browse, f"{specs_dir}/changes/{where}")
    for document in dict.fromkeys(_DOCUMENT_LINK.findall(decisions)):
        links += _link("Design", browse, document)
    return "\n\n".join([*(part for part in parts if part), *links])


def _group_body(group: TaskGroup) -> str:
    parts = [f"Tier: {group.tier}", "\n".join(group.body).strip()]
    if tests := named_test_paths(group):
        parts.insert(1, "Tests: " + ", ".join(tests))
    return "\n\n".join(parts)


def _group_state(change: str, number: int, units: Sequence[Unit]) -> tuple[str, tuple[str, ...]]:
    """The state of a group's item from the units that cover it, whatever their order. A
    superseded unit and one that builds nothing say nothing while another unit covers the group;
    an unfinished unit beats a finished one, and the group is done when all of them are."""
    covering = [unit for unit in units if (change, number) in carried_pairs(unit)]
    live = [
        unit
        for unit in covering
        if not unit.superseded_by and _UNIT_STATES[unit.state][0] != "removed"
    ]
    if not live:
        return ("removed", ()) if covering else ("new", ())
    unfinished = [unit for unit in live if _UNIT_STATES[unit.state][0] != "done"]
    if not unfinished:
        return _UNIT_STATES[UnitState.MERGED]
    return _UNIT_STATES[max((unit.state for unit in unfinished), key=_UNFINISHED_ORDER.index)]


def _change_state(states: Sequence[str], *, archived: bool) -> str:
    """New before any unit starts, done once the change is archived and every group that is
    still wanted is done, active between."""
    live = [state for state in states if state != "removed"]
    if archived and live and all(state == "done" for state in live):
        return "done"
    return "new" if all(state == "new" for state in live) else "active"


def _parent(
    section: TrackerSection, level: str, name: str, group: int, epics: Mapping[str, str]
) -> tuple[str | None, str | None]:
    """The marker of the wanted parent of an item and the recorded id of the epic, which is
    the parent of the first level when the section sets one."""
    above = section.parent_level(level)
    if above == "epic":
        return None, epics.get(name)
    if above == "group":
        return f"{name}:{group}", None
    return (name if above else None), None


def wanted_board(
    section: TrackerSection,
    changes_dir: Path,
    changes: Sequence[str],
    units: Sequence[Unit],
    *,
    browse: Callable[[str], str],
    epics: Mapping[str, str] | None = None,
    archived: Collection[str] = (),
    tracking_dir: Path | None = None,
) -> tuple[WantedItem, ...]:
    """The items wanted for `changes` (folders of `changes_dir`) on the levels of `section`,
    outermost level first. `browse` gives the address of a path of the planning repo (empty when
    the host has none, which leaves the link out), `epics` maps a change to the epic id its
    tracker file records and `archived` names the changes that are archived. `tracking_dir`
    holds the pipeline's copy of each change's `tasks.md` (`<state dir>/changes`), whose boxes
    are the ones it ticks; a change with no copy there takes its boxes from the repository
    file."""
    epics = epics or {}
    per_level: dict[str, list[WantedItem]] = {level: [] for level in section.levels}
    for name in changes:
        folder = change_folder(changes_dir, name)
        tasks_file = folder / TASKS_FILE
        if tasks_file.is_file():
            groups, _ = validate_tasks(tasks_file)
            tasks = read_tasks(tasks_file, name)
        else:
            groups, tasks = [], []
        copy = tracking_dir / name / TASKS_FILE if tracking_dir else None
        ticked = (
            {task.key: task.done for task in read_tasks(copy, name)}
            if copy and copy.is_file()
            else {}
        )
        states = {group.number: _group_state(name, group.number, units) for group in groups}

        if "change" in per_level:
            marker_of, epic_id = _parent(section, "change", name, 0, epics)
            per_level["change"].append(
                WantedItem(
                    level="change",
                    marker=name,
                    title=_change_title(name, folder),
                    body=_change_body(folder, changes_dir, browse),
                    state=_change_state(
                        [state for state, _ in states.values()], archived=name in archived
                    ),
                    parent_marker=marker_of,
                    parent_id=epic_id,
                )
            )
        if "group" in per_level:
            for group in groups:
                state, tags = states[group.number]
                marker_of, epic_id = _parent(section, "group", name, group.number, epics)
                per_level["group"].append(
                    WantedItem(
                        level="group",
                        marker=f"{name}:{group.number}",
                        title=group.title,
                        body=_group_body(group),
                        state=state,
                        tags=tags,
                        parent_marker=marker_of,
                        parent_id=epic_id,
                    )
                )
        if "task" in per_level:
            for task in tasks:
                marker_of, epic_id = _parent(section, "task", name, task.group, epics)
                per_level["task"].append(
                    WantedItem(
                        level="task",
                        marker=task.key,
                        title=task.text.splitlines()[0],
                        body=task.text,
                        state="done" if ticked.get(task.key, task.done) else "new",
                        parent_marker=marker_of,
                        parent_id=epic_id,
                    )
                )
    return tuple(item for items in per_level.values() for item in items)
