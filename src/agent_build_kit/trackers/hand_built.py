"""A merged pull request on items a person holds closes the work they built by hand (spec:
unit-claim): it records the hold and the hand merge `abk external hand-off` and `abk external
done` would."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from agent_build_kit import trackers
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.external_done import HandMergeRefused, record_hand_merge
from agent_build_kit.pipeline.external_file import (
    Hold,
    HoldRefused,
    add_hold,
    already_held,
    done_groups,
)
from agent_build_kit.pipeline.tracker_file import mapping_target, read_for_target
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import MERGED, Unit
from agent_build_kit.trackers.config import section_for
from agent_build_kit.trackers.levels import group_key
from agent_build_kit.trackers.start_decision import RoundReads, mentions, others


def record_hand_built(
    inst: Installation,
    store: UnitStore,
    unit: Unit,
    held_items: Sequence[str],
    reads: RoundReads,
    log: Callable[[str], None],
) -> None:
    """For a unit skipped because a person holds items it covers: when a merged pull request, of
    any branch, carries the reference of a held group item, record a hold for that group (holder
    the person's display name, link the pull request) if none exists, then the merge. Groups
    already recorded done are left alone, so a later round records nothing more. A failure is
    logged and leaves the unit skipped."""
    section = section_for(unit.repo)
    if section is None or "group" not in section.levels:
        return
    if (tracker := trackers.for_repo(unit.repo)) is None:
        return
    forge, repo = inst.forge_of(unit.repo)
    merged = [pull for pull in reads.pulls(unit.repo, forge, repo) if pull.state == MERGED]
    if not merged:
        return
    sync = tracker.identity().name
    for member in unit.members():
        change_dir = inst.changes_dir / member.change
        found = read_for_target(change_dir, section.kind, mapping_target(section))
        if found is None:
            continue
        for pull in merged:
            text = f"{pull.title}\n{pull.body}"
            groups: list[int] = []
            holders: list[str] = []
            for group in member.groups:
                entry = found.groups.get(group_key(member.change, group))
                if entry is None or entry.id not in held_items or group in done_groups(change_dir):
                    continue
                if not mentions(text, section.link_line(entry.id)):
                    continue
                if who := others(tracker.get(entry.id), sync):
                    groups.append(group)
                    holders.extend(name for name in who if name not in holders)
            if not groups:
                continue
            hold = Hold(
                scope=tuple(groups),
                holder=", ".join(holders),
                link=forge.web_url(repo, pr=pull.number),
                since=datetime.now(UTC),
            )
            try:
                if not already_held(change_dir, hold):
                    add_hold(change_dir, hold)
                record_hand_merge(inst, store, member.change, groups, pr=pull.number)
            except (HoldRefused, HandMergeRefused) as error:
                log(f"{unit.id}: merged pull request {pull.number} not recorded: {error}")
