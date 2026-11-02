"""Whether a unit may start, given who owns the board items it covers (spec: unit-claim)."""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Sequence
from pathlib import Path
from typing import Literal

from agent_build_kit import config, forges, trackers
from agent_build_kit.config import active_checkout
from agent_build_kit.forges.base import Forge, PullRequest, RepoId
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.restack import remote_head
from agent_build_kit.pipeline.tracker_file import TrackerFile, mapping_target, read_for_target
from agent_build_kit.pipeline.units import Unit, branch_name, in_progress
from agent_build_kit.trackers.base import Tracker
from agent_build_kit.trackers.config import section_for
from agent_build_kit.trackers.levels import group_key, task_group_key

NO_BOARD_ITEM = "no board item yet"


class ClaimAttempt(Frozen):
    """One claim the decision made on an item and how it ended, for the unit's history."""

    item: str
    outcome: Literal["held", "lost", "released", "release failed"]


class StartDecision(Frozen):
    """The answer for one unit: start it, skip it (someone else owns it) or wait (the board is
    not ready). `items` holds the ids of the board items the reason is about; `attempts` every
    claim made and how it ended."""

    outcome: Literal["start", "skip", "wait"]
    reason: str = ""
    items: tuple[str, ...] = ()
    claimed: tuple[str, ...] = ()
    attempts: tuple[ClaimAttempt, ...] = ()


class RoundReads:
    """What one evaluation of the round has already asked the host: the pull requests of each
    repo, listed once, and the foreign-start answer of each unit, so a unit checked by the
    evaluation is not asked again when it is claimed."""

    def __init__(self) -> None:
        self._pulls: dict[str, list[PullRequest]] = {}
        self._foreign: dict[str, str] = {}

    def pulls(self, name: str, forge: Forge, repo: RepoId) -> list[PullRequest]:
        if name not in self._pulls:
            self._pulls[name] = forge.list_prs(repo)
        return self._pulls[name]

    def foreign(self, unit_id: str, ask: Callable[[], str]) -> str:
        if unit_id not in self._foreign:
            self._foreign[unit_id] = ask()
        return self._foreign[unit_id]


class Covered(Frozen):
    """The items a unit covers: every one checked for an owner, and those the claim acts on."""

    checked: tuple[str, ...]
    claimable: tuple[str, ...]


def _covered_ids(
    levels: Sequence[str], tracker_file: TrackerFile | None, change: str, groups: Sequence[int]
) -> Covered | None:
    """The items the groups cover at the levels checked, None when one has no item yet. The
    change item is checked only when it is the lowest level in use. A group whose task items are
    only partly mirrored does not wait: the items there are checked. The claim acts on the group
    items, or on the lowest level in use when `group` is not a level."""
    if tracker_file is None:
        return None
    if levels[-1] == "change":
        if not tracker_file.change:
            return None
        return Covered(checked=(tracker_file.change.id,), claimable=(tracker_file.change.id,))
    checked: list[str] = []
    claimable: list[str] = []
    for group in groups:
        key = group_key(change, group)
        if "group" in levels:
            if key not in tracker_file.groups:
                return None
            checked.append(tracker_file.groups[key].id)
            claimable.append(tracker_file.groups[key].id)
        tasks = [
            entry.id for task, entry in tracker_file.tasks.items() if task_group_key(task) == key
        ]
        if "task" in levels:
            if "group" not in levels and not tasks:
                return None
            checked.extend(tasks)
            if "group" not in levels:
                claimable.extend(tasks)
    return Covered(checked=tuple(checked), claimable=tuple(claimable))


def start_decision(
    unit: Unit,
    *,
    changes_dir: Path,
    claim: bool = True,
    for_repo: Callable[[str], tuple[Forge, RepoId]] | None = None,
    remote_head_of: Callable[[Path, str], str | None] | None = None,
    own_branches: Collection[str] = (),
    reads: RoundReads | None = None,
) -> StartDecision:
    """The decision for `unit` against the tracker of its repo, whose tracker files are under
    `changes_dir`; a repo with no tracker section starts it and makes no call. A failure to read
    the section, the tracker file or the board is a wait naming it, never a raise: the unit is
    not started without knowing who owns it, and no other unit is touched. Free items are
    claimed before the answer is start; a read-only caller passes `claim=False`. A pull request
    on one of `own_branches` is the kit's own and never a foreign start."""
    if unit.repo not in config.active().repos:
        return StartDecision(outcome="start")  # a repo the configuration lacks has no tracker
    try:
        return _decide(
            unit,
            changes_dir,
            claim,
            for_repo or forges.for_repo,
            remote_head_of or remote_head,
            own_branches,
            reads or RoundReads(),
        )
    except Exception as error:  # noqa: BLE001
        return StartDecision(outcome="wait", reason=f"tracker unavailable: {error}")


def _decide(
    unit: Unit,
    changes_dir: Path,
    claim: bool,
    for_repo: Callable[[str], tuple[Forge, RepoId]],
    remote_head_of: Callable[[Path, str], str | None],
    own_branches: Collection[str],
    reads: RoundReads,
) -> StartDecision:
    section = section_for(unit.repo)
    if section is None:
        return StartDecision(outcome="start")
    tracker = trackers.for_repo(unit.repo)
    if tracker is None:
        return StartDecision(outcome="start")
    wanted: list[str] = []
    claimable: list[str] = []
    for member in unit.members():
        found = read_for_target(changes_dir / member.change, section.kind, mapping_target(section))
        covered = _covered_ids(section.levels, found, member.change, member.groups)
        if covered is None:
            return StartDecision(outcome="wait", reason=NO_BOARD_ITEM)
        wanted.extend(covered.checked)
        claimable.extend(covered.claimable)
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
        foreign = reads.foreign(
            unit.id,
            lambda: _foreign_start(
                unit, wanted, section.link_line, for_repo, remote_head_of, own_branches, reads
            ),
        )
        if foreign:
            return StartDecision(outcome="skip", reason=foreign, items=tuple(wanted))
    if not claim:
        return StartDecision(outcome="start", items=tuple(wanted))
    return _claim_all(tracker, sync, claimable, wanted)


def _mentions(text: str, reference: str) -> bool:
    """Whether `text` carries `reference` as a whole: not the front of a longer id (`AB#12` in
    `AB#123`) and not the tail of a longer word."""
    return re.search(rf"(?<!\w){re.escape(reference)}(?!\d)", text) is not None


def _foreign_start(
    unit: Unit,
    wanted: Sequence[str],
    link_line: Callable[[str], str],
    for_repo: Callable[[str], tuple[Forge, RepoId]],
    remote_head_of: Callable[[Path, str], str | None],
    own_branches: Collection[str],
    reads: RoundReads,
) -> str:
    """Why the unit was already started elsewhere, by the branch's name or by an open pull
    request on another branch that carries a covered item's reference; empty when nothing was.
    The kit's own branches are never foreign. A remote that cannot be asked raises, so the unit
    waits."""
    branch = branch_name(unit)
    forge, repo = for_repo(unit.repo)
    head = remote_head_of(active_checkout(config.active().repos[unit.repo].path), branch)
    if head is None:
        raise RuntimeError(f"the remote could not be asked about {branch}")
    if head:
        return f"foreign branch {branch} exists on the remote"
    if (found := forge.find_pr(repo, head=branch)) is not None:
        return f"foreign pull request {found} is on branch {branch}"
    for pull in reads.pulls(unit.repo, forge, repo):
        if pull.state != "open" or pull.head in own_branches:
            continue
        for item_id in wanted:
            if _mentions(f"{pull.title}\n{pull.body}", link_line(item_id)):
                return (
                    f"foreign pull request {pull.number} on branch {pull.head} "
                    f"carries item {item_id}"
                )
    return ""


def _release(tracker: Tracker, sync: str, made: Sequence[str]) -> list[ClaimAttempt]:
    """Clear the claims made for a unit, each only while it is still the sync account's alone, so
    a person who took the item meanwhile keeps it. A failure on one item does not stop the
    others or hide the reason the claims are released."""
    released: list[ClaimAttempt] = []
    for item_id in made:
        try:
            if tracker.get(item_id).assignees == (sync,):
                tracker.set_assignee(item_id, "")
                released.append(ClaimAttempt(item=item_id, outcome="released"))
        except Exception:  # noqa: BLE001
            released.append(ClaimAttempt(item=item_id, outcome="release failed"))
    return released


def _claim_all(
    tracker: Tracker, sync: str, claimable: Sequence[str], wanted: Sequence[str]
) -> StartDecision:
    """Claim each claimable item not already the sync account's, never retrying. A claim not
    held, or a failure while claiming, releases the ones made for this unit: the first skips it
    naming who holds the item, the second makes it wait."""
    claimed: list[str] = []
    attempts: list[ClaimAttempt] = []
    try:
        for item_id in claimable:
            if tracker.get(item_id).assignees == (sync,):
                continue
            if not tracker.claim(item_id):
                attempts.append(ClaimAttempt(item=item_id, outcome="lost"))
                holders = [who for who in tracker.get(item_id).assignees if who != sync]
                attempts.extend(_release(tracker, sync, claimed))
                return StartDecision(
                    outcome="skip",
                    reason=f"claim lost: assigned to {', '.join(holders) or 'someone else'}",
                    items=(item_id,),
                    attempts=tuple(attempts),
                )
            claimed.append(item_id)
            attempts.append(ClaimAttempt(item=item_id, outcome="held"))
    except Exception as error:  # noqa: BLE001
        attempts.extend(_release(tracker, sync, claimed))
        return StartDecision(
            outcome="wait", reason=f"tracker unavailable: {error}", attempts=tuple(attempts)
        )
    return StartDecision(
        outcome="start", items=tuple(wanted), claimed=tuple(claimed), attempts=tuple(attempts)
    )


def start_gate(
    unit: Unit,
    graph: Sequence[Unit],
    *,
    changes_dir: Path,
    claim: bool = False,
    reads: RoundReads | None = None,
) -> StartDecision:
    """The one rule the round applies: a unit already in progress is the kit's and is not asked;
    any other is decided by `start_decision`, with the branches of the graph's units as the
    kit's own."""
    if in_progress(unit, graph):
        return StartDecision(outcome="start")
    own = {branch_name(other) for other in graph if other.id != unit.id}
    own |= {branch for other in graph if (branch := getattr(other, "branch", ""))}
    return start_decision(unit, changes_dir=changes_dir, claim=claim, own_branches=own, reads=reads)
