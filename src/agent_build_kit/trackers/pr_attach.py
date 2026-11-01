"""The board items a unit's pull request is linked to (spec: tracker-push).

Which items follow `pr_links` and the levels (`levels.link_targets`) over the groups the unit
built; the ids come from each change's `tracker.yaml`. The description names them in the form
the tracker's host turns into a link, and the pull request is attached to each item once, which
a machine-local record keeps from repeating.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_build_kit import trackers
from agent_build_kit.pipeline.file_lock import atomic_write_text, file_lock
from agent_build_kit.pipeline.task_progress import TASKS_FILE
from agent_build_kit.pipeline.tracker_file import TrackerFile, read_tracker
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.work_graph import read_tasks
from agent_build_kit.trackers.config import TrackerConfigError, section_for
from agent_build_kit.trackers.levels import link_targets

ATTACHED_NAME = "tracker-pr-links.json"
RELATION = "pull_request"
# The words a pull request description uses so the host links the item, by tracker kind.
_LINE = {"azure_devops": "AB#{}", "github": "Part of #{}"}


def _recorded_id(found: TrackerFile, key: str) -> str | None:
    entry = found.groups.get(key) or found.tasks.get(key)
    if entry is None and found.change is not None and ":" not in key:
        entry = found.change
    return entry.id if entry else None


def link_items(unit: StoredUnit, changes_dir: Path) -> tuple[tuple[str, str], ...]:
    """The key and recorded item id of each board item the unit's pull request links to; empty
    for a repo with no tracker or no recorded item."""
    try:
        section = section_for(unit.repo)
    except TrackerConfigError:
        return ()
    if section is None:
        return ()
    found: list[tuple[str, str]] = []
    for member in unit.members():
        recorded = read_tracker(changes_dir / member.change)
        if recorded is None:
            continue
        tasks = (
            read_tasks(changes_dir / member.change / TASKS_FILE, member.change)
            if "task" in section.levels
            else []
        )
        built = {
            group: tuple(task.number for task in tasks if task.group == group)
            for group in member.groups
        }
        for key in link_targets(section.levels, section.pr_links, member.change, built):
            if (item_id := _recorded_id(recorded, key)) is not None:
                found.append((key, item_id))
    return tuple(found)


def link_lines(unit: StoredUnit, changes_dir: Path) -> str:
    """One line for each linked item, in the form the tracker's host links; empty when none."""
    try:
        section = section_for(unit.repo)
    except TrackerConfigError:
        return ""
    template = _LINE.get(section.kind) if section else None
    if template is None:
        return ""
    return "\n".join(template.format(item_id) for _, item_id in link_items(unit, changes_dir))


def attach_pull_request(
    unit: StoredUnit, *, changes_dir: Path, state_dir: Path, pr_url: str
) -> tuple[str, ...]:
    """Attach the pull request to each item `pr_links` names for the groups the unit built,
    once each, recording it in the machine-local state; the keys attached this time."""
    items = link_items(unit, changes_dir)
    if not items or (tracker := trackers.for_repo(unit.repo)) is None:
        return ()
    path = state_dir / ATTACHED_NAME
    attached: list[str] = []
    with file_lock(path.with_name(f"{path.name}.lock")):
        try:
            done = json.loads(path.read_text())
        except (OSError, ValueError):
            done = {}
        for key, item_id in items:
            if key in done.get(pr_url, []):
                continue
            tracker.link(item_id, RELATION, pr_url)
            done.setdefault(pr_url, []).append(key)
            atomic_write_text(path, json.dumps(done, indent=2, sort_keys=True))
            attached.append(key)
    return tuple(attached)
