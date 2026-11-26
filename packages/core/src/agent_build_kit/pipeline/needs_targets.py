"""Where each `Needs:` line of the active changes leads, and which of them are unmet."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import UnitState
from agent_build_kit.pipeline.work_graph import group_needs, names_own_change, validate_tasks
from agent_build_kit.trackers.folders import archived_entries

NOT_PLANNED = "not_planned"
NO_GROUP = "no_group"
NO_TASKS = "no_tasks"
OUTLINE = "outline"
MISSING = "missing"

_NOT_COVERING = (UnitState.UNPLANNED, UnitState.RETIRED)


class UnmetNeed(Frozen):
    """One `Needs:` line whose target group is not covered by a unit and not archived."""

    change: str
    group: int
    line: int
    target: str
    target_group: int
    outcome: str
    wording: str


def _wording(outcome: str, target: str, group: int, plan_state: str) -> str:
    named = f"{target} group {group}"
    return {
        NOT_PLANNED: f"{named} has no unit yet ({plan_state})",
        NO_GROUP: f"{target} has no group {group}",
        NO_TASKS: f"{target} has no tasks.md yet",
        OUTLINE: f"{target} is an outline, which nothing plans",
        MISSING: f"no change, archived change or outline is named {target}",
    }[outcome]


def unmet_needs(
    tasks_files: Sequence[Path],
    units: Sequence[StoredUnit],
    changes_dir: Path,
    outlines: Collection[str],
    plan_states: Mapping[str, str],
) -> list[UnmetNeed]:
    """Each unmet `Needs:` line of `tasks_files`, with its outcome: `not_planned`, `no_group`,
    `no_tasks`, `outline` or `missing`."""
    covered = {
        (member.change.lower(), group)
        for unit in units
        if unit.state not in _NOT_COVERING
        for member in unit.members()
        for group in member.groups
    }
    folders = (
        {entry.name.lower(): entry for entry in changes_dir.iterdir() if entry.is_dir()}
        if changes_dir.is_dir()
        else {}
    )
    folders.pop("archive", None)
    archived = {name.lower() for name in archived_entries(changes_dir)}
    outline_names = {name.lower() for name in outlines}
    states = {name.lower(): state for name, state in plan_states.items()}
    target_groups: dict[str, set[int]] = {}
    found: list[UnmetNeed] = []
    for path in tasks_files:
        for group, needs in sorted(group_needs(path).items()):
            for need in needs:
                if names_own_change(need, path) or (need.change, need.group) in covered:
                    continue
                folder = folders.get(need.change)
                if folder is None:
                    if need.change in archived:
                        continue
                    outcome = OUTLINE if need.change in outline_names else MISSING
                elif not (folder / "tasks.md").is_file():
                    outcome = NO_TASKS
                else:
                    if need.change not in target_groups:
                        parsed, _ = validate_tasks(folder / "tasks.md")
                        target_groups[need.change] = {g.number for g in parsed}
                    outcome = NOT_PLANNED if need.group in target_groups[need.change] else NO_GROUP
                state = states.get(need.change, "never planned")
                found.append(
                    UnmetNeed(
                        change=path.parent.name,
                        group=group,
                        line=need.line,
                        target=need.change,
                        target_group=need.group,
                        outcome=outcome,
                        wording=_wording(outcome, need.change, need.group, state),
                    )
                )
    return found


def needs_messages(path: Path, unmet: Sequence[UnmetNeed]) -> tuple[list[str], list[str]]:
    """The `abk tags` errors and warnings for the unmet lines of the tasks file `path`."""
    errors: list[str] = []
    warnings: list[str] = []
    for item in unmet:
        if item.change != path.parent.name or item.outcome == NOT_PLANNED:
            continue
        named = f"{item.target} group {item.target_group}"
        where = f"{path}:line {item.line}: "
        if item.outcome == OUTLINE:
            errors.append(
                f"{where}Needs: {named} names an outline, and a change cannot wait on one; "
                f"detail {item.target} as a change first, or make {item.change} an outline "
                f"with `Waits on: {named}`"
            )
        elif item.outcome == MISSING:
            errors.append(
                f"{where}Needs: {named}: no change, archived change or outline is named "
                f"{item.target}"
            )
        elif item.outcome == NO_GROUP:
            errors.append(f"{where}Needs: {named}: {item.target} has no group {item.target_group}")
        elif item.outcome == NO_TASKS:
            warnings.append(
                f"warning: {where}Needs: {named}: {item.target} has no tasks.md yet, so the "
                "unit waits until it is planned"
            )
    return errors, warnings
