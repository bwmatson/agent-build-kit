"""The board items a unit's pull request is linked to (spec: tracker-push).

Which items follow `pr_links` and the levels (`levels.link_targets`) over the groups the unit
built; the ids come from each change's `tracker.yaml`. The description names them in the form
the section's kind gives (`link_line`), and the pull request is attached to each item once,
which a machine-local record keeps from repeating.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from agent_build_kit import trackers
from agent_build_kit.forges.transport import AuthError, HostError, HostUnavailable, RateLimited
from agent_build_kit.pipeline.file_lock import atomic_write_text, file_lock
from agent_build_kit.pipeline.task_progress import TASKS_FILE
from agent_build_kit.pipeline.tracker_file import TrackerFile, mapping_target, read_for_target
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.work_graph import read_tasks
from agent_build_kit.trackers.config import TrackerConfigError, section_for
from agent_build_kit.trackers.folders import change_folder
from agent_build_kit.trackers.levels import link_targets

ATTACHED_NAME = "tracker-pr-links.json"
RELATION = "pull_request"


def _recorded_id(found: TrackerFile, key: str) -> str | None:
    entry = found.groups.get(key) or found.tasks.get(key)
    if entry is None and found.change is not None and ":" not in key:
        entry = found.change
    return entry.id if entry else None


def link_items(unit: StoredUnit, changes_dir: Path) -> tuple[tuple[str, str], ...]:
    """The key and recorded item id of each board item the unit's pull request links to; empty
    for a repo with no tracker. A change whose tracker file or tasks file cannot be used, or
    records another board, has no links."""
    try:
        section = section_for(unit.repo)
    except TrackerConfigError:
        return ()
    if section is None:
        return ()
    target = mapping_target(section)
    found: list[tuple[str, str]] = []
    for member in unit.members():
        folder = change_folder(changes_dir, member.change)
        try:
            recorded = read_for_target(folder, section.kind, target)
            tasks = (
                read_tasks(folder / TASKS_FILE, member.change) if "task" in section.levels else []
            )
        except Exception:  # noqa: BLE001 — a file problem costs this change its links only
            continue
        if recorded is None:
            continue
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
    items = link_items(unit, changes_dir)
    if not items:
        return ""
    section = section_for(unit.repo)
    assert section is not None  # items exist only for a repo with a section
    return "\n".join(section.link_line(item_id) for _, item_id in items)


def _recorded(path: Path) -> dict[str, list[str]]:
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _record(path: Path, pr_url: str, key: str) -> None:
    with file_lock(path.with_name(f"{path.name}.lock")):
        done = _recorded(path)
        if key not in done.setdefault(pr_url, []):
            done[pr_url].append(key)
        atomic_write_text(path, json.dumps(done, indent=2, sort_keys=True))


def attach_pull_request(
    unit: StoredUnit,
    *,
    changes_dir: Path,
    state_dir: Path,
    pr_url: str,
    on_error: Callable[[str, Exception], None] | None = None,
) -> tuple[str, ...]:
    """Attach the pull request to each item `pr_links` names for the groups the unit built,
    once each, recording it in the machine-local state; the keys attached this time.

    A failure of one item goes to `on_error` (with the item's key) and the others go on; a rate
    limit, or a failure of the tracker as a whole, is raised for the caller to end the pass on.
    With no `on_error`, every failure is raised."""
    items = link_items(unit, changes_dir)
    if not items:
        return ()
    try:
        tracker = trackers.for_repo(unit.repo)
    except TrackerConfigError:
        return ()
    if tracker is None:
        return ()
    path = state_dir / ATTACHED_NAME
    with file_lock(path.with_name(f"{path.name}.lock")):
        done = _recorded(path)
    attached: list[str] = []
    for key, item_id in items:
        if key in done.get(pr_url, []):
            continue
        try:
            tracker.link(item_id, RELATION, pr_url)
        except (RateLimited, AuthError, HostError, HostUnavailable):
            raise
        except Exception as error:  # noqa: BLE001 — one item's failure does not stop the others
            if on_error is None:
                raise
            on_error(key, error)
            continue
        _record(path, pr_url, key)
        attached.append(key)
    return tuple(attached)
