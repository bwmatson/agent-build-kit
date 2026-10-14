"""Carrying a split plan out: files, unit records and plan records, checked before any write."""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Callable, Sequence
from pathlib import Path

from agent_build_kit.cli.pipeline import planned_hashes, record_plans
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.work_graph import NEEDS_LINE, specification_text
from agent_build_kit.split import scrubbing
from agent_build_kit.split.select import SplitPlan, moved_files

__all__ = ["CopyRefused", "CopyReport", "Preflight", "carry_out", "preflight"]


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


def _passes(source: Installation, plan: SplitPlan, scrub: bool) -> Callable[[str], str]:
    return scrubbing.scrubber(source, plan.repo) if scrub else lambda text: text


def _contents(source: Installation, plan: SplitPlan, scrub: bool) -> dict[Path, bytes]:
    """The bytes each moved file gets in the destination, by path under its specs directory."""
    scrub_text = _passes(source, plan, scrub)
    contents: dict[Path, bytes] = {}
    for path in moved_files(source, plan):
        text = scrubbing.read_text(path) if scrub else None
        data = path.read_bytes() if text is None else scrub_text(text).encode()
        contents[path.relative_to(source.specs_dir)] = data
    return contents


def _records(source: Installation, plan: SplitPlan, scrub: bool) -> list[StoredUnit]:
    """The moved unit records as they would be written."""
    scrub_text = _passes(source, plan, scrub)
    moved = [
        unit
        for unit in UnitStore(source.state_dir / "units.json").all()
        if unit.id in plan.units_moved
    ]
    return [scrubbing.scrub_record(unit, scrub_text) for unit in moved] if scrub else moved


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
    for relative, data in _contents(source, plan, scrub).items():
        target = destination.specs_dir / relative
        if target.is_file() and target.read_bytes() != data:
            errors.append(f"conflict: {relative} differs in the destination")

    store = UnitStore(destination.state_dir / "units.json")
    held = {unit.id: unit for unit in store.all()}
    records = _records(source, plan, scrub)
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
        for field in ("depends_on", "needs"):
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
        for line in (source.changes_dir / name / "tasks.md").read_text().splitlines():
            found = NEEDS_LINE.match(line.strip())
            if found and found["change"].lower() not in {*moved_changes, *destination_changes}:
                errors.append(
                    _dangling(
                        f"change {name} `Needs: {found['change']} group {found['group']}`",
                        found["change"],
                    )
                )

    staying = [
        unit
        for unit in UnitStore(source.state_dir / "units.json").all()
        if unit.id not in moved_units
    ]
    edges = [
        f"unit {unit.id} {field} names {target}, which moves"
        for unit in staying
        for field in ("depends_on", "needs")
        for target in getattr(unit, field)
        if target in moved_units
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

    contents = _contents(source, plan, scrub)
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

    records = _records(source, plan, scrub)
    UnitStore(destination.state_dir / "units.json").import_units(records)

    recorded = planned_hashes(source)
    plans = {
        name: {
            "hash": hashlib.sha256(
                specification_text(contents[Path("changes") / name / "tasks.md"].decode()).encode()
            ).hexdigest(),
            "attempts": 0,
            "ok": True,
        }
        for name in plan.changes_moved
        if recorded.get(name, {}).get("ok")
    }
    if plans:
        record_plans(destination, plans)
    return CopyReport(
        files_copied=copied,
        files_unchanged=unchanged,
        units_imported=len(records),
        plans_written=len(plans),
    )
