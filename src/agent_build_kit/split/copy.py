"""Carrying a split plan out: files, unit records and plan records, checked before any write."""

from __future__ import annotations

import shutil
from collections.abc import Callable, Sequence
from pathlib import Path

from agent_build_kit.cli.pipeline import plan_digest, planned_hashes, record_plans
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.work_graph import group_needs
from agent_build_kit.split import scrubbing
from agent_build_kit.split.select import SplitPlan, moved_files, moved_records

__all__ = [
    "CopyRefused",
    "CopyReport",
    "Preflight",
    "carry_out",
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


class Preflight(Frozen):
    """Every conflict and dangling edge (the errors) and every staying edge into the moved set
    (a warning, an error under `remove`), found before the first write."""

    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


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


def unit_records(source: Installation, plan: SplitPlan, scrub: bool) -> list[StoredUnit]:
    """The moved unit records as they would be written."""
    scrub_text = _passes(source, plan, scrub)
    moved = moved_records(source, plan)
    return [scrubbing.scrub_record(unit, scrub_text) for unit in moved] if scrub else moved


def _plans_to_write(source: Installation, destination: Installation, plan: SplitPlan) -> dict:
    """The moved changes' plan records the destination does not already hold as they would be
    written: the hash is of the text as it is in the destination."""
    held = planned_hashes(destination)
    recorded = planned_hashes(source)
    wanted = {
        name: {
            "hash": plan_digest(destination.changes_dir / name / "tasks.md"),
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
    if any(unit.id not in held for unit in unit_records(source, plan, scrub)):
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
    records = unit_records(source, plan, scrub)
    errors += [
        f"conflict: unit {unit.id} differs in the destination"
        for unit in records
        if unit.id in held and held[unit.id] != unit
    ]

    moved_units = set(plan.units_moved)
    moved_changes = set(plan.changes_moved)
    here = {*held, *moved_units}
    destination_changes = (
        {p.name for p in destination.changes_dir.iterdir() if p.is_dir()}
        if destination.changes_dir.is_dir()
        else set()
    )
    for unit in records:
        for field in ("depends_on", "needs", "superseded_by"):
            errors += [
                _dangling(f"unit {unit.id} {field}", target)
                for target in getattr(unit, field)
                if target not in here
            ]
        errors += [
            _dangling(f"unit {unit.id} joined", member.change)
            for member in unit.joined
            if member.change not in {*moved_changes, *destination_changes}
        ]
    for name in plan.changes_moved:
        for group, needs in group_needs(source.changes_dir / name / "tasks.md").items():
            errors += [
                _dangling(
                    f"change {name} group {group} `Needs: {need.change} group {need.group}`",
                    need.change,
                )
                for need in needs
                if need.change not in moved_changes
                and (source.changes_dir / need.change / "tasks.md").is_file()
                and not (destination.changes_dir / need.change / "tasks.md").is_file()
            ]

    staying = [
        unit
        for unit in UnitStore(source.state_dir / "units.json").all()
        if unit.id not in moved_units
    ]
    edges = [
        f"unit {unit.id} {field} names {target}, which moves"
        for unit in staying
        for field in ("depends_on", "needs", "superseded_by")
        for target in getattr(unit, field)
        if target in moved_units
    ]
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
        warnings=() if remove else tuple(edges),
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

    records = unit_records(source, plan, scrub)
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
