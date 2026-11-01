"""The tick's tracker step and the dirty mark a state change leaves for it (spec: tracker-push).

A state change only marks its repo's mirror dirty, in the repo's machine-local file; the step,
which runs once a round after the label sweep, pushes the board. No tracker call is made from a
state change. The mark is a record for now: the step runs every round whether or not it is set,
and clears it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from agent_build_kit import telemetry, trackers
from agent_build_kit.forges.transport import RateLimited
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.planning_sync import in_repo_name
from agent_build_kit.pipeline.task_progress import TASKS_FILE, progress_root
from agent_build_kit.pipeline.tracker_file import mapping_target, read_for_target
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import UnitState
from agent_build_kit.pipeline.work_graph import validate_tasks
from agent_build_kit.trackers.base import REPO_FAILURES, Tracker
from agent_build_kit.trackers.config import TrackerConfigError, TrackerSection, section_for
from agent_build_kit.trackers.folders import archived_entries, tracker_read_dir
from agent_build_kit.trackers.pr_attach import attach_pull_request
from agent_build_kit.trackers.reconciler import (
    ERRORS_COUNTER,
    PassReport,
    read_snapshot,
    reconcile,
    snapshot_path,
    update_snapshot,
)
from agent_build_kit.trackers.wanted_board import wanted_board

DIRTY_KEY = "dirty"
_WITH_PR = (UnitState.IN_REVIEW, UnitState.MERGED)


def mark_dirty(state_dir: Path, repo: str) -> None:
    """Record that a unit of `repo` changed state since its last pass. Makes no tracker call."""
    update_snapshot(snapshot_path(state_dir, repo), lambda kept: kept.update({DIRTY_KEY: True}))


def is_dirty(state_dir: Path, repo: str) -> bool:
    """Whether a state change of `repo` is waiting for a pass."""
    return bool(read_snapshot(snapshot_path(state_dir, repo)).get(DIRTY_KEY))


def _clear_dirty(state_dir: Path, repo: str) -> None:
    def drop(kept: dict[str, object]) -> None:
        kept.pop(DIRTY_KEY, None)

    if is_dirty(state_dir, repo):
        update_snapshot(snapshot_path(state_dir, repo), drop)


def _has_tracker(repo: str) -> bool:
    try:
        return trackers.enabled(repo)
    except TrackerConfigError:
        return False


def note_state_change(inst: Installation, repo: str) -> None:
    """Mark `repo`'s mirror dirty when it names a tracker; otherwise leave no trace."""
    if _has_tracker(repo):
        mark_dirty(inst.state_dir, repo)


def _has_group_for(tasks: Path, repo: str) -> bool:
    try:
        groups, _ = validate_tasks(tasks)
    except Exception:  # noqa: BLE001 — a change that does not parse is not mirrored
        return False
    return any(group.repo == repo for group in groups)


def _changes_of(inst: Installation, repo: str) -> list[str]:
    """The changes in flight with a task group for `repo`."""
    return [tasks.parent.name for tasks in inst.tasks_files() if _has_group_for(tasks, repo)]


def _unfinished_archived(
    inst: Installation,
    repo: str,
    section: TrackerSection,
    units: Sequence[StoredUnit],
    live: Sequence[str],
    archive: Mapping[str, Path],
    browse: Callable[[str], str],
) -> list[str]:
    """The archived changes of `repo` whose board was mirrored and does not yet show the change
    and every group as done, so a change that finishes and is archived in one round still ends
    done. A group the plan no longer wants is not waited for, and a tracker file that records
    another board leaves the change out."""
    target = mapping_target(section)
    found: list[str] = []
    for name in archive:
        if name in live:
            continue
        try:
            recorded = read_for_target(
                tracker_read_dir(inst.changes_dir, inst.state_dir, name, archive),
                section.kind,
                target,
            )
        except Exception:  # noqa: BLE001 — an unusable file is not this step's to report
            continue
        if recorded is None:
            continue
        synced = {name: recorded.change, **recorded.groups, **recorded.tasks}
        pending = {
            marker
            for marker, entry in synced.items()
            if entry and entry.fields.get("state") != "done"
        }
        if not pending or not _has_group_for(archive[name] / TASKS_FILE, repo):
            continue
        wanted = wanted_board(
            section,
            inst.changes_dir,
            [name],
            units,
            browse=browse,
            archived=[name],
            tracking_dir=progress_root(inst),
        )
        removed = {item.marker for item in wanted if item.state == "removed"}
        if pending - removed:
            found.append(name)
    return found


def _browse_of(inst: Installation) -> Callable[[str], str]:
    """The address of a path of the planning repo on its code host, from the host's own forge;
    empty when the planning repo is separate from the listed repos, which gives no address."""
    home = in_repo_name(inst)
    if home is None:
        return lambda path: ""
    forge, repo_id = inst.forge_of(home)
    branch = inst.repo(home).default_branch
    return lambda path: forge.browse_url(repo_id, branch=branch, path=path)


def _attach_all(
    inst: Installation,
    repo: str,
    units: Sequence[StoredUnit],
    archive: Mapping[str, Path],
    log: Callable[[str], None],
) -> None:
    """Attach the pull request of each unit of `repo` that has one, containing failures: one
    item's is logged and counted, a rate limit or a failed tracker ends the repo's attaches."""
    forge, repo_id = inst.forge_of(repo)
    tracker: Tracker | None = None

    def failed(key: str, error: Exception) -> None:
        telemetry.count(ERRORS_COUNTER, repo=repo)
        log(f"tracker {repo}: pull request not attached to {key}: {error}")

    for unit in units:
        if unit.repo != repo or unit.pr is None or unit.state not in _WITH_PR:
            continue
        try:
            if tracker is None:
                tracker = trackers.for_repo(repo)
            if tracker is None:
                return
            attach_pull_request(
                unit,
                changes_dir=inst.changes_dir,
                state_dir=inst.state_dir,
                pr_url=forge.web_url(repo_id, pr=unit.pr),
                on_error=failed,
                tracker=tracker,
                archive=archive,
            )
        except TrackerConfigError:
            return
        except RateLimited as error:
            log(f"tracker {repo}: rate limited, attaching resumes next tick: {error}")
            return
        except REPO_FAILURES as error:
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
    archive = archived_entries(inst.changes_dir)
    browse = _browse_of(inst)
    archived = _unfinished_archived(inst, repo, section, units, live, archive, browse)
    report: PassReport = reconcile(
        repo,
        changes_dir=inst.changes_dir,
        changes=[*live, *archived],
        units=units,
        browse=browse,
        state_dir=inst.state_dir,
        tracking_dir=progress_root(inst),
        archived=archived,
        log=log,
        create_cap=section.create_cap,
    )
    if not (report.stopped or report.failed):
        _attach_all(inst, repo, units, archive, log)


def sync_trackers(
    inst: Installation, units: Sequence[StoredUnit], *, log: Callable[[str], None] = print
) -> None:
    """Push the wanted board of every repo that names a tracker, then attach the pull requests
    of its units; a repo without one is passed over at once, with no call and no file written.
    One repo's failure is logged and leaves the others to run."""
    named = [name for name in inst.repos if _has_tracker(name)]
    for repo in named:
        try:
            _clear_dirty(inst.state_dir, repo)
            _sync_repo(inst, repo, units, log)
        except TrackerConfigError as error:
            log(f"tracker {repo}: skipped: {error}")
        except Exception as error:  # noqa: BLE001 — a repo's failure never stops another's
            telemetry.count(ERRORS_COUNTER, repo=repo)
            log(f"tracker {repo}: failed: {type(error).__name__}: {error}")
