"""Whether a unit may start, given who owns the board items it covers (spec: unit-claim)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal

from agent_build_kit import config, forges, trackers
from agent_build_kit.config import active_checkout
from agent_build_kit.forges.base import Forge, RepoId
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.restack import remote_head
from agent_build_kit.pipeline.tracker_file import TrackerFile, mapping_target, read_for_target
from agent_build_kit.pipeline.units import Unit, branch_name, in_progress
from agent_build_kit.trackers.base import Tracker
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


def start_decision(
    unit: Unit,
    *,
    changes_dir: Path,
    claim: bool = True,
    for_repo: Callable[[str], tuple[Forge, RepoId]] | None = None,
    remote_head_of: Callable[[Path, str], str | None] | None = None,
) -> StartDecision:
    """The decision for `unit` against the tracker of its repo, whose tracker files are under
    `changes_dir`; a repo with no tracker section starts it and makes no call. A failure to read
    the section, the tracker file or the board is a wait naming it, never a raise: the unit is
    not started without knowing who owns it, and no other unit is touched. Free items are
    claimed before the answer is start; a read-only caller passes `claim=False`."""
    if unit.repo not in config.active().repos:
        return StartDecision(outcome="start")  # a repo the configuration lacks has no tracker
    try:
        return _decide(
            unit, changes_dir, claim, for_repo or forges.for_repo, remote_head_of or remote_head
        )
    except Exception as error:  # noqa: BLE001
        return StartDecision(outcome="wait", reason=f"tracker unavailable: {error}")


def _decide(
    unit: Unit,
    changes_dir: Path,
    claim: bool,
    for_repo: Callable[[str], tuple[Forge, RepoId]],
    remote_head_of: Callable[[Path, str], str | None],
) -> StartDecision:
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
    if not (getattr(unit, "branch", "") or getattr(unit, "pr", None) is not None):
        foreign = _foreign_start(unit, wanted, section.link_line, for_repo, remote_head_of)
        if foreign:
            return StartDecision(outcome="skip", reason=foreign, items=tuple(wanted))
    if not claim:
        return StartDecision(outcome="start", items=tuple(wanted))
    return _claim_all(tracker, sync, wanted)


def _foreign_start(
    unit: Unit,
    wanted: Sequence[str],
    link_line: Callable[[str], str],
    for_repo: Callable[[str], tuple[Forge, RepoId]],
    remote_head_of: Callable[[Path, str], str | None],
) -> str:
    """Why the unit was already started elsewhere, by the branch's name or by a pull request that
    carries a covered item's reference; empty when nothing was. A remote that cannot be asked
    raises, so the unit waits."""
    branch = branch_name(unit)
    forge, repo = for_repo(unit.repo)
    head = remote_head_of(active_checkout(config.active().repos[unit.repo].path), branch)
    if head is None:
        raise RuntimeError(f"the remote could not be asked about {branch}")
    if head:
        return f"someone else started it: branch {branch} exists on the remote"
    if (found := forge.find_pr(repo, head=branch)) is not None:
        return f"someone else started it: pull request {found} is on branch {branch}"
    for pull in forge.list_prs(repo):
        if pull.state == "closed":
            continue
        for item_id in wanted:
            if link_line(item_id) in f"{pull.title}\n{pull.body}":
                return (
                    f"someone else started it: pull request {pull.number} "
                    f"on branch {pull.head} carries item {item_id}"
                )
    return ""


def _claim_all(tracker: Tracker, sync: str, wanted: Sequence[str]) -> StartDecision:
    """Claim each item not already the sync account's, never retrying. A claim not held releases
    the ones made for this unit and skips it, naming who holds the item."""
    claimed: list[str] = []
    for item_id in wanted:
        if tracker.get(item_id).assignees == (sync,):
            continue
        if not tracker.claim(item_id):
            holders = [who for who in tracker.get(item_id).assignees if who != sync]
            for made in claimed:
                tracker.set_assignee(made, "")
            return StartDecision(
                outcome="skip",
                reason=f"claim lost: assigned to {', '.join(holders) or 'someone else'}",
                items=(item_id,),
            )
        claimed.append(item_id)
    return StartDecision(outcome="start", items=tuple(wanted), claimed=tuple(claimed))


def start_gate(
    unit: Unit, graph: Sequence[Unit], *, changes_dir: Path, claim: bool = False
) -> StartDecision:
    """The one rule the round applies: a unit already in progress is the kit's and is not asked;
    any other is decided by `start_decision`."""
    if in_progress(unit, graph):
        return StartDecision(outcome="start")
    return start_decision(unit, changes_dir=changes_dir, claim=claim)
