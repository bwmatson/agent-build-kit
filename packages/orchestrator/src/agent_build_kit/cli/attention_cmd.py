"""`abk attention`: what needs a person now, one item a line, each with the command that acts on it.

The pipeline recovers from most stops itself (a wait that ends, a login renewed, a flaky test's
fix merged). What is left is scattered across `abk status`; this gathers it, and leaves out what
resolves without anyone: a failed unit waiting on a dependency is requeued when the wait ends, and
work handed to someone outside the kit is theirs. Items that hold up the most units come first.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import datetime, timedelta

from agent_build_kit import run_support
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline import outlines, plan_review, spans
from agent_build_kit.pipeline.archive import ARCHIVE_FAILURES, read_archive_failures
from agent_build_kit.pipeline.external_file import held_units
from agent_build_kit.pipeline.manual_steps import manual_status_line, unmet_steps
from agent_build_kit.pipeline.needs_targets import (
    NO_TASKS,
    NOT_PLANNED,
    OUTLINE,
    UnmetNeed,
)
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import (
    FAILED,
    HELD,
    MERGED,
    PLANNED,
    RUNNING,
    waiting_on,
    waiting_on_me,
)

# A running unit no run has held for this long is listed: it is waiting for something to resume.
IDLE_AFTER = timedelta(hours=1)
# The most characters of a unit's note an item shows.
NOTE_LIMIT = 200


class Item(Frozen):
    """One thing that needs a person: what it is about, what is wrong, and what to run."""

    subject: str
    what: str
    action: str
    blocks: int = 0


def _note(unit: StoredUnit) -> str:
    note = " ".join((unit.note or "").split())
    return note[:NOTE_LIMIT] + ("…" if len(note) > NOTE_LIMIT else "")


def _since(unit: StoredUnit) -> datetime | None:
    if not unit.history:
        return None
    raw = unit.history[-1].get("at")
    try:
        return datetime.fromisoformat(str(raw)) if raw else None
    except ValueError:
        return None


def _needs_action(need: UnmetNeed) -> str:
    """The command or edit that resolves one unmet `Needs:` line."""
    where = f"openspec/changes/{need.change}/tasks.md"
    if need.outcome == NOT_PLANNED:
        return f"abk replan {need.target}; or edit {need.target}'s tasks.md as its plan says"
    if need.outcome == NO_TASKS:
        return f"write {need.target}'s tasks.md; the unit waits until it is planned"
    if need.outcome == OUTLINE:
        return (
            f"detail {need.target} as a change, or make {need.change} an outline with "
            f"`Waits on: {need.target} group {need.target_group}`"
        )
    return f"fix the Needs: line in {where}"


def attention_items(
    inst: Installation,
    units: Sequence[StoredUnit],
    *,
    idle: set[str],
    now: datetime,
) -> list[Item]:
    """Everything that needs a person, the items holding up the most units first."""
    items: list[Item] = []
    for unit in units:
        if unit.state not in (FAILED, HELD, RUNNING, PLANNED, MERGED):
            continue

        def blocking(unit: StoredUnit = unit) -> int:
            return len(waiting_on_me(unit, units))

        if unit.state == FAILED and not waiting_on(unit, units):
            items.append(
                Item(
                    subject=unit.id,
                    what=f"failed: {_note(unit)}",
                    action=f"abk explain {unit.id}; then abk requeue {unit.id} "
                    "(--rework --note TEXT to change what it does)",
                    blocks=blocking(),
                )
            )
        elif unit.state == HELD:
            items.append(
                Item(
                    subject=unit.id,
                    what=f"held ({unit.held_by or 'for a person'}): {_note(unit)}",
                    action=f"abk explain {unit.id}; then abk requeue {unit.id} or abk release "
                    f"{unit.id}",
                    blocks=blocking(),
                )
            )
        elif unit.state == RUNNING and unit.id in idle:
            since = _since(unit)
            if since is not None and now - since >= IDLE_AFTER:
                items.append(
                    Item(
                        subject=unit.id,
                        what=f"running with no worker since {since:%Y-%m-%d %H:%M}: {_note(unit)}",
                        action=f"abk explain {unit.id}",
                        blocks=blocking(),
                    )
                )
        if unit.state == PLANNED:
            for step in unmet_steps(unit):
                items.append(
                    Item(
                        subject=unit.id,
                        what=manual_status_line(step),
                        action=f"abk manual done {step.slug}"
                        if not step.check
                        else "do the step, or fix its check, as its runbook says",
                        blocks=blocking(),
                    )
                )
        if unit.state == MERGED and unit.branch_kept:
            items.append(
                Item(
                    subject=unit.id,
                    what=f"merged, branch kept: {unit.branch_kept}",
                    action="remove the worktree that has the branch checked out "
                    "(git worktree remove PATH); the pipeline then deletes the branch",
                )
            )
    # A held change matters only while it has units that have not started, and not when someone
    # outside the kit holds all of those: then the work is theirs.
    external = held_units(inst.changes_dir, units)
    by_change: dict[str, int] = {}
    for unit in units:
        if unit.unstarted and unit.id not in external:
            by_change[unit.change] = by_change.get(unit.change, 0) + 1
    for change, review in plan_review.held_changes(inst).items():
        if not by_change.get(change):
            continue
        items.append(
            Item(
                subject=change,
                what=f"plan review: {len(review.blockers)} blocker(s) the pipeline could not "
                "repair; its units that have not started wait",
                action=f"abk review-plan show {change}; edit its tasks.md, or "
                f"abk review-plan clear {change} --note TEXT",
                blocks=by_change.get(change, 0),
            )
        )
    for reading in outlines.ready_outlines(inst, units):
        items.append(
            Item(
                subject=reading.outline.name,
                what="outline ready to detail: the work it waits on is near enough to build",
                action=f"abk outlines; then detail {reading.outline.name} as a change",
            )
        )
    for change, failure in read_archive_failures(inst.state_dir / ARCHIVE_FAILURES).items():
        items.append(
            Item(
                subject=change,
                what=f"archive failed: {failure.get('error', '')}",
                action="fix the change's files (often a delta spec header that does not match "
                f"the living spec); it is tried again once they change: openspec validate {change}",
            )
        )
    from agent_build_kit.cli.pipeline import _unmet_needs, given_up_plans

    built = {
        (member.change, group)
        for unit in units
        if unit.state == MERGED
        for member in unit.members()
        for group in member.groups
    }
    for need in _unmet_needs(inst):
        if (need.change, need.group) in built:
            continue
        waiting = [
            unit
            for unit in units
            if unit.state == PLANNED
            and any(m.change == need.change and need.group in m.groups for m in unit.members())
        ]
        items.append(
            Item(
                subject=f"{need.change} group {need.group}",
                what=f"Needs: {need.wording}",
                action=_needs_action(need),
                blocks=len(waiting),
            )
        )
    for change, record in given_up_plans(inst).items():
        reason = record.get("reason") or "no reason recorded"
        items.append(
            Item(
                subject=change,
                what=f"planning gave up: {reason}",
                action=f"edit openspec/changes/{change}/tasks.md as the reason says (planning "
                f"tries again once it changes), or abk replan {change}",
            )
        )
    return sorted(items, key=lambda item: (-item.blocks, item.subject))


def items_for(inst: Installation) -> list[Item]:
    """`attention_items` over the installation's stored units, now."""
    from agent_build_kit.cli.pipeline import _idle_units

    units = run_support.store_for(inst).all()
    return attention_items(inst, units, idle=_idle_units(inst, units, ()), now=spans.clock.now())


def cmd_attention(args: argparse.Namespace, inst: Installation) -> int:
    items = items_for(inst)
    if args.json:
        print(json.dumps([item.model_dump() for item in items], indent=2))
        return 0
    if not items:
        print("nothing needs a person")
        return 0
    print(f"{len(items)} item(s) need a person:")
    for item in items:
        held = f" (holds up {item.blocks})" if item.blocks else ""
        print(f"- {item.subject}{held}: {item.what}\n    → {item.action}")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "attention", help="list what needs a person now, each with the command that acts on it"
    )
    parser.add_argument("--json", action="store_true", help="print the items as JSON")
    parser.set_defaults(func=cmd_attention)
