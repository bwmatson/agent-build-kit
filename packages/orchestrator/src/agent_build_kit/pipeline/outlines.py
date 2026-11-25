"""Outlines: the far-out work a planning repo keeps as `<outlines>/<name>/proposal.md`, how many
units ahead of being buildable each one is, and which detailed changes touch the same paths
(spec: outlines-are-detailed-one-unit-ahead). Reads only; makes no model call."""

from __future__ import annotations

import re
from collections.abc import Sequence
from fnmatch import fnmatchcase

from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.group_paths import TICKED, line_globs, line_paths
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import UnitState


class WaitsOn(Frozen):
    """One `Waits on: <change or outline> group <n>` line."""

    target: str
    group: int


class Outline(Frozen):
    """One outline as written: the lines a tool reads, and the lines that did not parse."""

    name: str
    initiative: str = ""
    its_part: str = ""
    groups: tuple[int, ...] = ()
    waits_on: tuple[WaitsOn, ...] = ()
    touches: tuple[str, ...] = ()
    reworks: tuple[str, ...] = ()
    # Lines that did not parse (a `Waits on:` with no group number), ignored for the distance.
    unparsed: tuple[str, ...] = ()


class Reading(Frozen):
    """An outline with its distance: None on a cycle, which also names the cycle."""

    outline: Outline
    distance: int | None
    ready: bool
    cycle: tuple[str, ...] = ()
    # Prerequisite names that are neither a change nor an outline.
    not_found: tuple[str, ...] = ()
    # Each detailed `Waits on:` target and group with the units it contributes.
    ahead: tuple[tuple[str, int, int], ...] = ()


class Overlap(Frozen):
    """A detailed change and an outline whose paths overlap."""

    change: str
    outline: str
    reworks: int
    # More than two `Reworks:` lines: the outline is detailed sooner.
    promote_earlier: bool


# A unit in one of these states is not ahead of an outline: its pull request is up or further.
_NOT_AHEAD = frozenset(
    {
        UnitState.IN_REVIEW,
        UnitState.SETTLING,
        UnitState.MERGED,
        UnitState.SATISFIED,
        UnitState.CLOSED,
        UnitState.RETIRED,
        UnitState.UNPLANNED,
    }
)
_WAITS = re.compile(r"^Waits on:\s*(\S+)\s+group\s+(\d+)\b")
_SKETCH = re.compile(r"^(\d+)\.\s")


def _parse(name: str, text: str) -> Outline:
    initiative = ""
    part: list[str] = []
    groups: list[int] = []
    waits: list[WaitsOn] = []
    touches: list[str] = []
    reworks: list[str] = []
    unparsed: list[str] = []
    section = ""
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip().lower()
        elif line.startswith("Initiative:"):
            initiative = line.removeprefix("Initiative:").strip()
        elif line.startswith("Waits on:"):
            found = _WAITS.match(line)
            if found:
                waits.append(WaitsOn(target=found.group(1), group=int(found.group(2))))
            else:
                unparsed.append(line)
        elif line.startswith("Touches:"):
            touches += TICKED.findall(line)
        elif line.startswith("Reworks:"):
            reworks.append(line.removeprefix("Reworks:").strip())
        elif section == "its part":
            part.append(line)
        elif section.startswith("groups") and (sketch := _SKETCH.match(line)):
            groups.append(int(sketch.group(1)))
    return Outline(
        name=name,
        initiative=initiative,
        its_part="\n".join(part).strip(),
        groups=tuple(groups),
        waits_on=tuple(waits),
        touches=tuple(touches),
        reworks=tuple(reworks),
        unparsed=tuple(unparsed),
    )


def read_outlines(inst: Installation) -> list[Outline]:
    """Every folder under `planning.outlines` that holds a `proposal.md`, in name order."""
    folder = inst.root / inst.config.planning.outlines
    return [
        _parse(proposal.parent.name, proposal.read_text())
        for proposal in sorted(folder.glob("*/proposal.md"))
    ]


def _units_ahead(
    units: Sequence[StoredUnit], by_id: dict[str, StoredUnit], change: str, group: int
) -> int:
    """The units carrying `group` of `change`, with their ancestors, each once, that are not yet
    in review; one per group up to `group` when no unit carries it."""
    carrying = [
        unit.id
        for unit in units
        if (unit.change == change and group in unit.groups)
        or any(m.change == change and group in m.groups for m in unit.joined)
    ]
    if not carrying:
        return group
    seen: set[str] = set()
    stack = carrying
    while stack:
        uid = stack.pop()
        if uid in seen or uid not in by_id:
            continue
        seen.add(uid)
        stack.extend(by_id[uid].depends_on)
    return sum(1 for uid in seen if by_id[uid].state not in _NOT_AHEAD)


def readings(inst: Installation, units: Sequence[StoredUnit]) -> list[Reading]:
    """Each outline's distance over `units`, nearest first, then by name."""
    outlines = {outline.name: outline for outline in read_outlines(inst)}
    detailed = {path.parent.name for path in inst.tasks_files()}
    by_id = {unit.id: unit for unit in units}
    memo: dict[str, int | tuple[str, ...]] = {}
    # Each outline's `Waits on:` targets with the units each contributes, kept off a cycle.
    shown: dict[str, tuple[tuple[str, int, int], ...]] = {}

    def resolve(name: str, path: tuple[str, ...]) -> int | tuple[str, ...]:
        if name in memo:
            return memo[name]
        if name in path:
            return (*path[path.index(name) :], name)
        longest = 0
        contributions: list[tuple[str, int, int]] = []
        for wait in outlines[name].waits_on:
            if wait.target in detailed:
                ahead = _units_ahead(units, by_id, wait.target, wait.group)
            elif wait.target in outlines:
                inner = resolve(wait.target, (*path, name))
                if isinstance(inner, tuple):
                    memo[name] = inner
                    return inner
                sketched = sum(1 for g in outlines[wait.target].groups if g <= wait.group)
                ahead = sketched + inner
            else:
                continue
            contributions.append((wait.target, wait.group, ahead))
            longest = max(longest, ahead)
        memo[name] = longest
        shown[name] = tuple(contributions)
        return longest

    lead = inst.config.planning.outline_lead_units
    found: list[Reading] = []
    for name, outline in outlines.items():
        result = resolve(name, ())
        distance = result if isinstance(result, int) else None
        found.append(
            Reading(
                outline=outline,
                distance=distance,
                ready=distance is not None and distance <= lead,
                cycle=result if isinstance(result, tuple) else (),
                not_found=tuple(
                    w.target
                    for w in outline.waits_on
                    if w.target not in detailed and w.target not in outlines
                ),
                ahead=shown.get(name, ()),
            )
        )
    return sorted(found, key=lambda r: (r.distance is None, r.distance or 0, r.outline.name))


def ready_outlines(inst: Installation, units: Sequence[StoredUnit]) -> list[Reading]:
    """The readings whose distance is at most `planning.outline_lead_units`."""
    return [reading for reading in readings(inst, units) if reading.ready]


def _overlap(a: str, b: str) -> bool:
    if fnmatchcase(a, b) or fnmatchcase(b, a):
        return True
    left, right = a.rstrip("/"), b.rstrip("/")
    return left.startswith(right + "/") or right.startswith(left + "/")


def overlaps(inst: Installation) -> list[Overlap]:
    """For each detailed change, each outline whose `Touches:` overlaps a path its tasks name."""
    outlines = read_outlines(inst)
    found: list[Overlap] = []
    for tasks in inst.tasks_files():
        named = [
            path
            for line in tasks.read_text().splitlines()
            for path in (*line_paths(line), *line_globs(line))
        ]
        for outline in outlines:
            if any(_overlap(path, token) for path in named for token in outline.touches):
                found.append(
                    Overlap(
                        change=tasks.parent.name,
                        outline=outline.name,
                        reworks=len(outline.reworks),
                        promote_earlier=len(outline.reworks) > 2,
                    )
                )
    return found
