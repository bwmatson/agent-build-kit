"""The tick's tracker step and the dirty mark a state change leaves for it (spec: tracker-push).

A state change only marks the mirror dirty, in a machine-local file; the step, which runs once a
round after the label sweep, pushes the board. No tracker call is made from a state change. The
mark is a record for now: the step runs every round whether or not it is set, and clears it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from agent_build_kit import telemetry, trackers
from agent_build_kit.forges.transport import AuthError, HostError, HostUnavailable, RateLimited
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.file_lock import atomic_write_text
from agent_build_kit.pipeline.planning_repo import repo_sharing
from agent_build_kit.pipeline.task_progress import progress_root
from agent_build_kit.pipeline.tracker_file import read_tracker
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import UnitState
from agent_build_kit.pipeline.work_graph import validate_tasks
from agent_build_kit.trackers.config import TrackerConfigError, section_for
from agent_build_kit.trackers.folders import archived_entries
from agent_build_kit.trackers.pr_attach import attach_pull_request
from agent_build_kit.trackers.reconciler import ERRORS_COUNTER, PassReport, reconcile

DIRTY_NAME = "tracker-dirty"
_WITH_PR = (UnitState.IN_REVIEW, UnitState.MERGED)
_WHOLE_TRACKER = (AuthError, HostError, HostUnavailable)


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


def _has_group_for(tasks: Path, repo: str) -> bool:
    try:
        groups, _ = validate_tasks(tasks)
    except Exception:  # noqa: BLE001 — a change that does not parse is not mirrored
        return False
    return any(group.repo == repo for group in groups)


def _changes_of(inst: Installation, repo: str) -> list[str]:
    """The changes in flight with a task group for `repo`."""
    return [tasks.parent.name for tasks in inst.tasks_files() if _has_group_for(tasks, repo)]


def _unfinished_archived(inst: Installation, repo: str, live: Sequence[str]) -> list[str]:
    """The archived changes of `repo` whose board was mirrored and does not yet show the change
    and every group as done, so a change that finishes and is archived in one round still ends
    done."""
    found: list[str] = []
    for name, folder in archived_entries(inst.changes_dir).items():
        if name in live or not _has_group_for(folder / "tasks.md", repo):
            continue
        try:
            recorded = read_tracker(folder)
        except Exception:  # noqa: BLE001 — an unusable file is reported by the pass itself
            recorded = None
        if recorded is None:
            continue
        synced = [recorded.change, *recorded.groups.values(), *recorded.tasks.values()]
        if any(entry and entry.fields.get("state") != "done" for entry in synced):
            found.append(name)
    return found


def _repo_url(inst: Installation, repo: str) -> str:
    """Where the planning repo's files are browsed: its code host's page for the default branch."""
    home = repo_sharing(inst.checkouts, inst.root) or repo
    forge, repo_id = inst.forge_of(home)
    return f"{forge.web_url(repo_id)}/tree/{inst.repo(home).default_branch}"


def _attach_all(
    inst: Installation, repo: str, units: Sequence[StoredUnit], log: Callable[[str], None]
) -> None:
    """Attach the pull request of each unit of `repo` that has one, containing failures: one
    item's is logged and counted, a rate limit or a failed tracker ends the repo's attaches."""
    forge, repo_id = inst.forge_of(repo)

    def failed(key: str, error: Exception) -> None:
        telemetry.count(ERRORS_COUNTER, repo=repo)
        log(f"tracker {repo}: pull request not attached to {key}: {error}")

    for unit in units:
        if unit.repo != repo or unit.pr is None or unit.state not in _WITH_PR:
            continue
        try:
            attach_pull_request(
                unit,
                changes_dir=inst.changes_dir,
                state_dir=inst.state_dir,
                pr_url=forge.web_url(repo_id, pr=unit.pr),
                on_error=failed,
            )
        except RateLimited as error:
            log(f"tracker {repo}: rate limited, attaching resumes next tick: {error}")
            return
        except _WHOLE_TRACKER as error:
            telemetry.count(ERRORS_COUNTER, repo=repo)
            log(f"tracker {repo}: the tracker failed, no pull request attached this tick: {error}")
            return
        except Exception as error:  # noqa: BLE001 — a host answers in its own errors
            failed(unit.id, error)


def _sync_repo(
    inst: Installation, repo: str, units: Sequence[StoredUnit], log: Callable[[str], None]
) -> None:
    section = section_for(repo)
    if section is None:
        return
    live = _changes_of(inst, repo)
    archived = _unfinished_archived(inst, repo, live)
    report: PassReport = reconcile(
        repo,
        changes_dir=inst.changes_dir,
        changes=[*live, *archived],
        units=units,
        repo_url=_repo_url(inst, repo),
        state_dir=inst.state_dir,
        tracking_dir=progress_root(inst),
        archived=archived,
        log=log,
        create_cap=section.create_cap,
    )
    if not (report.stopped or report.failed):
        _attach_all(inst, repo, units, log)


def sync_trackers(
    inst: Installation, units: Sequence[StoredUnit], *, log: Callable[[str], None] = print
) -> None:
    """Push the wanted board of every repo that names a tracker, then attach the pull requests
    of its units; a repo without one is passed over at once, with no call and no file written.
    One repo's failure is logged and leaves the others to run."""
    named = [name for name in inst.repos if _has_tracker(name)]
    if not named:
        return
    (inst.state_dir / DIRTY_NAME).unlink(missing_ok=True)
    for repo in named:
        try:
            _sync_repo(inst, repo, units, log)
        except TrackerConfigError as error:
            log(f"tracker {repo}: skipped: {error}")
        except Exception as error:  # noqa: BLE001 — a repo's failure never stops another's
            telemetry.count(ERRORS_COUNTER, repo=repo)
            log(f"tracker {repo}: failed: {type(error).__name__}: {error}")
