"""Carrying a split plan out: files, unit records and plan records, checked before any write."""

from __future__ import annotations

import shutil
from collections.abc import Callable, Sequence
from enum import StrEnum
from pathlib import Path

from agent_build_kit.cli.pipeline import plan_digest, planned_hashes, record_plans
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline import loaded_code
from agent_build_kit.pipeline.loaded_code import LoadedCode
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import MERGED, merge_loaded
from agent_build_kit.pipeline.work_graph import group_needs
from agent_build_kit.split import scrubbing
from agent_build_kit.split.select import (
    SplitPlan,
    archive_change_name,
    moved_files,
    moved_records,
)

__all__ = [
    "CopyRefused",
    "CopyReport",
    "DroppedEdge",
    "EdgeReason",
    "Preflight",
    "carry_out",
    "dropped_edges",
    "file_contents",
    "moved_plan_records",
    "outstanding",
    "preflight",
    "unit_records",
]


class CopyRefused(ValueError):
    """The preflight found errors; nothing was written."""

    def __init__(self, errors: Sequence[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = tuple(errors)


class EdgeReason(StrEnum):
    """Why the target of a dropped edge stays in the source."""

    REPO = "repo"
    PROJECT = "project"
    KEPT_CHANGE = "kept_change"


class DroppedEdge(Frozen):
    """One dependency a moved unit's record loses on its way: a merged unit that stays."""

    unit: str
    field: str
    target: str
    reason: EdgeReason = EdgeReason.REPO


class Preflight(Frozen):
    """Every conflict and dangling edge (the errors) and every staying edge into the moved set
    (a warning, an error under `remove`), found before the first write; `dropped` is each
    dependency the written records leave out."""

    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    dropped: tuple[DroppedEdge, ...] = ()


class CopyReport(Frozen):
    files_copied: int = 0
    files_unchanged: int = 0
    units_imported: int = 0
    plans_written: int = 0


def moved_plan_records(source: Installation, plan: SplitPlan) -> tuple[str, ...]:
    """The moved changes the source holds an ok plan record for: the ones whose record moves."""
    recorded = planned_hashes(source)
    return tuple(name for name in plan.changes_moved if recorded.get(name, {}).get("ok"))


def _passes(source: Installation, plan: SplitPlan, scrub: bool) -> Callable[[str], str]:
    return scrubbing.scrubber(source, plan.repo) if scrub else lambda text: text


def file_contents(source: Installation, plan: SplitPlan, scrub: bool) -> dict[Path, bytes]:
    """The bytes each moved file gets in the destination, by path under its specs directory."""
    scrub_text = _passes(source, plan, scrub)
    contents: dict[Path, bytes] = {}
    for path in moved_files(source, plan):
        text = scrubbing.read_text(path) if scrub else None
        data = path.read_bytes() if text is None else scrub_text(text).encode()
        contents[path.relative_to(source.specs_dir)] = data
    return contents


# The lists of a unit record that name other units and take a dropped edge, and the ones the
# plan reports it for (`merge_needs` is a subset of `needs`).
_EDGE_FIELDS = ("depends_on", "needs", "merge_needs")
_REPORTED_FIELDS = ("depends_on", "needs")


def _kept_changes(plan: SplitPlan) -> set[str]:
    """The mixed changes the source keeps, active ones and archive entries by change name."""
    return {
        *(item.name for item in plan.changes_mixed if item.name not in plan.changes_moved),
        *(
            archive_change_name(item.name)
            for item in plan.archive_mixed
            if item.name not in plan.archive_moved
        ),
    }


def _stays_because(parent: StoredUnit, plan: SplitPlan, kept: set[str]) -> EdgeReason | None:
    """Why a unit that does not move stays, when that is a reason an edge may be dropped for:
    its repo, its project, or a mixed change kept in the source; None for any other."""
    if parent.repo != plan.repo:
        return EdgeReason.REPO
    if parent.id in plan.units_blocking:
        return None
    if plan.project is not None and parent.project != plan.project:
        return EdgeReason.PROJECT
    if parent.id in plan.units_staying and any(m.change in kept for m in parent.members()):
        return EdgeReason.KEPT_CHANGE
    return None


def _satisfied_history(
    source: Installation, destination: Installation, plan: SplitPlan
) -> tuple[dict[str, dict[str, EdgeReason]], set[str]]:
    """For each moved unit, the dependency ids its record drops, each with the reason its
    target stays: a merged unit that stays for its repo, project or a kept mixed change, whose
    merge the tick has loaded, that neither moves nor is in the destination. Also the ids of
    such units whose merge is not yet loaded."""
    everything = UnitStore(source.state_dir / "units.json").all()
    by_id = {unit.id: unit for unit in everything}
    held = UnitStore(destination.state_dir / "units.json").all()
    here = {*plan.units_moved, *(u.id for u in held)}
    kept = _kept_changes(plan)
    loaded: LoadedCode | None = loaded_code.current()
    dropped: dict[str, dict[str, EdgeReason]] = {}
    unloaded: set[str] = set()
    for unit in moved_records(source, plan):
        targets = {t for field in _EDGE_FIELDS for t in getattr(unit, field)}
        found: dict[str, EdgeReason] = {}
        for target in targets - here:
            parent = by_id.get(target)
            if parent is None or parent.state != MERGED:
                continue
            if (reason := _stays_because(parent, plan, kept)) is None:
                continue
            if loaded is None or merge_loaded(parent, everything, loaded):
                found[target] = reason
            else:
                unloaded.add(target)
        dropped[unit.id] = found
    return dropped, unloaded


def _edges_in(
    source: Installation, plan: SplitPlan, dropped: dict[str, dict[str, EdgeReason]]
) -> tuple[DroppedEdge, ...]:
    return tuple(
        DroppedEdge(unit=unit.id, field=field, target=target, reason=dropped[unit.id][target])
        for unit in moved_records(source, plan)
        for field in _REPORTED_FIELDS
        for target in getattr(unit, field)
        if target in dropped[unit.id]
    )


def _records_without(
    source: Installation,
    plan: SplitPlan,
    dropped: dict[str, dict[str, EdgeReason]],
    scrub: bool,
) -> list[StoredUnit]:
    scrub_text = _passes(source, plan, scrub)
    moved = [
        unit.model_copy(
            update={
                field: tuple(t for t in getattr(unit, field) if t not in dropped[unit.id])
                for field in _EDGE_FIELDS
            }
        )
        for unit in moved_records(source, plan)
    ]
    return [scrubbing.scrub_record(unit, scrub_text) for unit in moved] if scrub else moved


def dropped_edges(
    source: Installation, destination: Installation, plan: SplitPlan
) -> tuple[DroppedEdge, ...]:
    """The edges of the moved units' records that the destination's copy leaves out."""
    dropped, _ = _satisfied_history(source, destination, plan)
    return _edges_in(source, plan, dropped)


def unit_records(
    source: Installation, destination: Installation, plan: SplitPlan, scrub: bool
) -> list[StoredUnit]:
    """The moved unit records as they would be written, without the dropped edges."""
    dropped, _ = _satisfied_history(source, destination, plan)
    return _records_without(source, plan, dropped, scrub)


def _plans_to_write(source: Installation, destination: Installation, plan: SplitPlan) -> dict:
    """The moved changes' plan records the destination does not already hold as they would be
    written: the hash is of the text as it is in the destination."""
    held = planned_hashes(destination)
    recorded = planned_hashes(source)
    wanted = {
        name: {
            "hash": plan_digest(destination.changes_dir / name / "tasks.md", inst=destination),
            "sizing": recorded[name].get("sizing", ""),
            "attempts": 0,
            "ok": True,
        }
        for name in moved_plan_records(source, plan)
    }
    return {name: record for name, record in wanted.items() if held.get(name) != record}


def outstanding(
    source: Installation, destination: Installation, plan: SplitPlan, *, scrub: bool = False
) -> bool:
    """Whether carrying the plan out would write anything to the destination's files, unit
    records or plan records."""
    if any(
        not (destination.specs_dir / relative).is_file()
        for relative in file_contents(source, plan, scrub)
    ):
        return True
    held = {unit.id for unit in UnitStore(destination.state_dir / "units.json").all()}
    if any(unit.id not in held for unit in unit_records(source, destination, plan, scrub)):
        return True
    return bool(_plans_to_write(source, destination, plan))


def preflight(
    source: Installation,
    destination: Installation,
    plan: SplitPlan,
    *,
    scrub: bool = False,
    remove: bool = False,
) -> Preflight:
    """What would refuse the copy, reading both installations and writing neither."""
    errors: list[str] = []
    for relative, data in file_contents(source, plan, scrub).items():
        target = destination.specs_dir / relative
        if target.is_file() and target.read_bytes() != data:
            errors.append(f"conflict: {relative} differs in the destination")

    store = UnitStore(destination.state_dir / "units.json")
    held = {unit.id: unit for unit in store.all()}
    dropped, unloaded = _satisfied_history(source, destination, plan)
    records = _records_without(source, plan, dropped, scrub)
    errors += [
        f"conflict: unit {unit.id} differs in the destination"
        for unit in records
        if unit.id in held and held[unit.id] != unit
    ]

    moved_units = set(plan.units_moved)
    moved_changes = set(plan.changes_moved)
    archive_dir = destination.changes_dir / "archive"
    destination_archive = (
        [p.name for p in archive_dir.iterdir() if p.is_dir()] if archive_dir.is_dir() else []
    )
    here = {*held, *moved_units}
    destination_changes = (
        {p.name for p in destination.changes_dir.iterdir() if p.is_dir()}
        if destination.changes_dir.is_dir()
        else set()
    )
    known_changes = {
        *moved_changes,
        *destination_changes,
        *map(archive_change_name, plan.archive_moved),
        *map(archive_change_name, destination_archive),
        *plan.changes_no_directory,
    }
    for unit in records:
        for field in ("depends_on", "needs", "superseded_by"):
            for target in getattr(unit, field):
                if target in here:
                    continue
                if target in unloaded and field != "superseded_by":
                    errors.append(
                        f"unit {unit.id} {field} names {target}, a merged unit that stays "
                        "whose merge the tick has not loaded: run a tick and try again"
                    )
                else:
                    errors.append(_dangling(f"unit {unit.id} {field}", target))
        errors += [
            _dangling(f"unit {unit.id} joined", member.change)
            for member in unit.joined
            if member.change not in known_changes
        ]
    notes: list[str] = []
    covering = UnitStore(source.state_dir / "units.json").all()
    loaded: LoadedCode | None = loaded_code.current()
    for name in plan.changes_moved:
        for group, needs in group_needs(source.changes_dir / name / "tasks.md").items():
            for need in needs:
                if (
                    need.change in moved_changes
                    or not (source.changes_dir / need.change / "tasks.md").is_file()
                    or (destination.changes_dir / need.change / "tasks.md").is_file()
                ):
                    continue
                what = f"change {name} group {group} `Needs: {need.change} group {need.group}`"
                builders = [
                    unit
                    for unit in covering
                    if any(
                        m.change == need.change and need.group in m.groups for m in unit.members()
                    )
                ]
                if builders and all(unit.state == MERGED for unit in builders):
                    if loaded is None or all(merge_loaded(u, covering, loaded) for u in builders):
                        notes.append(
                            f"{what} names {need.change}, which stays: its group is merged "
                            "history and the line is kept, inert in the destination"
                        )
                    else:
                        errors.append(
                            f"{what} names {need.change}, whose merged group's merge the tick "
                            "has not loaded: run a tick and try again"
                        )
                else:
                    errors.append(_dangling(what, need.change))

    everything = UnitStore(source.state_dir / "units.json").all()
    merged_moved = {
        unit.id for unit in everything if unit.id in moved_units and unit.state == MERGED
    }
    staying = [unit for unit in everything if unit.id not in moved_units]
    unit_edges = [
        (target in merged_moved, f"unit {unit.id} {field} names {target}, which moves")
        for unit in staying
        for field in ("depends_on", "needs", "superseded_by")
        for target in getattr(unit, field)
        if target in moved_units
    ]
    harmless = [line for merged, line in unit_edges if merged]
    edges = [line for merged, line in unit_edges if not merged]
    edges += [
        f"change {name} group {group} `Needs: {need.change} group {need.group}` names "
        f"{need.change}, which moves"
        for tasks in sorted(source.changes_dir.glob("*/tasks.md"))
        if (name := tasks.parent.name) not in moved_changes
        for group, needs in group_needs(tasks).items()
        for need in needs
        if need.change in moved_changes
    ]
    return Preflight(
        errors=tuple(errors + (edges if remove else [])),
        warnings=tuple([*notes, *(harmless if remove else harmless + edges)]),
        dropped=_edges_in(source, plan, dropped),
    )


def _dangling(what: str, target: str) -> str:
    return f"{what} names {target}, which is neither moved nor in the destination"


def carry_out(
    source: Installation,
    destination: Installation,
    plan: SplitPlan,
    *,
    scrub: bool = False,
) -> CopyReport:
    """Copy the plan's files, import its unit records and write its plan records;
    raises `CopyRefused` with every error and writes nothing when the preflight finds one."""
    found = preflight(source, destination, plan, scrub=scrub)
    if found.errors:
        raise CopyRefused(found.errors)

    contents = file_contents(source, plan, scrub)
    copied = unchanged = 0
    for relative, data in contents.items():
        target = destination.specs_dir / relative
        if target.is_file():
            unchanged += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        shutil.copymode(source.specs_dir / relative, target)
        copied += 1

    records = unit_records(source, destination, plan, scrub)
    UnitStore(destination.state_dir / "units.json").import_units(records)

    plans = _plans_to_write(source, destination, plan)
    if plans:
        record_plans(destination, plans)
    return CopyReport(
        files_copied=copied,
        files_unchanged=unchanged,
        units_imported=len(records),
        plans_written=len(plans),
    )
