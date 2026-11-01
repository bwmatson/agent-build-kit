"""The tick's tracker step and the dirty mark a state change leaves for it (spec: tracker-push).

A state change only marks the mirror dirty, in a machine-local file; the step, which runs once a
round after the label sweep, pushes the board. No tracker call is made from a state change.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from agent_build_kit import trackers
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.file_lock import atomic_write_text
from agent_build_kit.pipeline.planning_repo import repo_sharing
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import UnitState
from agent_build_kit.pipeline.work_graph import validate_tasks
from agent_build_kit.trackers.config import TrackerConfigError
from agent_build_kit.trackers.pr_attach import attach_pull_request
from agent_build_kit.trackers.reconciler import reconcile

DIRTY_NAME = "tracker-dirty"
_WITH_PR = (UnitState.IN_REVIEW, UnitState.MERGED)


def mark_dirty(state_dir: Path) -> None:
    """Record that a unit changed state since the last pass. Makes no tracker call."""
    atomic_write_text(state_dir / DIRTY_NAME, "1\n")


def is_dirty(state_dir: Path) -> bool:
    """Whether a state change is waiting for a pass."""
    return (state_dir / DIRTY_NAME).is_file()


def _has_tracker(repo: str) -> bool:
    try:
        return trackers.enabled(repo)
    except TrackerConfigError:
        return False


def note_state_change(inst: Installation) -> None:
    """Mark the mirror dirty when any repo names a tracker; otherwise leave no trace."""
    if any(_has_tracker(name) for name in inst.repos):
        mark_dirty(inst.state_dir)


def _changes_of(inst: Installation, repo: str) -> list[str]:
    """The changes in flight with a task group for `repo`."""
    found: list[str] = []
    for tasks in sorted(inst.changes_dir.glob("*/tasks.md")):
        try:
            groups, _ = validate_tasks(tasks)
        except Exception:  # noqa: BLE001 — a change that does not parse is not mirrored
            continue
        if any(group.repo == repo for group in groups):
            found.append(tasks.parent.name)
    return found


def _repo_url(inst: Installation, repo: str) -> str:
    """Where the planning repo's files are browsed: its code host's page for the default branch."""
    home = repo_sharing(inst.checkouts, inst.root) or repo
    forge, repo_id = inst.forge_of(home)
    return f"{forge.web_url(repo_id)}/tree/{inst.repo(home).default_branch}"


def sync_trackers(
    inst: Installation, units: Sequence[StoredUnit], *, log: Callable[[str], None] = print
) -> None:
    """Push the wanted board of every repo that names a tracker; a repo without one is passed
    over at once, with no call and no file written."""
    named = [name for name in inst.repos if _has_tracker(name)]
    if not named:
        return
    (inst.state_dir / DIRTY_NAME).unlink(missing_ok=True)
    for repo in named:
        reconcile(
            repo,
            changes_dir=inst.changes_dir,
            changes=_changes_of(inst, repo),
            units=units,
            repo_url=_repo_url(inst, repo),
            state_dir=inst.state_dir,
            tracking_dir=inst.state_dir / "changes",
            log=log,
        )
        forge, repo_id = inst.forge_of(repo)
        for unit in units:
            if unit.repo == repo and unit.pr is not None and unit.state in _WITH_PR:
                attach_pull_request(
                    unit,
                    changes_dir=inst.changes_dir,
                    state_dir=inst.state_dir,
                    pr_url=forge.web_url(repo_id, pr=unit.pr),
                )
