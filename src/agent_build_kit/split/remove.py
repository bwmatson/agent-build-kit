"""`--remove`: verify the copy, then take out of the source only what was moved."""

from __future__ import annotations

from collections.abc import Collection
from pathlib import Path

from agent_build_kit.cli.pipeline import planned_hashes, update_plans
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.split import copy
from agent_build_kit.split.select import SplitPlan, is_populated, moved_files, plan_split

__all__ = ["RemoveReport", "outstanding", "remove", "still_naming", "verify"]


class RemoveReport(Frozen):
    files_removed: int = 0
    units_removed: int = 0
    plans_removed: int = 0


def verify(
    source: Installation, destination: Installation, plan: SplitPlan, *, scrub: bool = False
) -> list[str]:
    """What in the destination does not match what the copy was to write: each file whose bytes
    differ or are missing, each unit record that differs; empty when the copy is whole."""
    problems = []
    for relative, data in copy.file_contents(source, plan, scrub).items():
        target = destination.specs_dir / relative
        if not target.is_file() or target.read_bytes() != data:
            problems.append(f"{relative} does not match in the destination")
    held = {unit.id: unit for unit in UnitStore(destination.state_dir / "units.json").all()}
    problems += [
        f"unit {unit.id} does not match in the destination"
        for unit in copy.unit_records(source, plan, scrub)
        if held.get(unit.id) != unit
    ]
    return problems


def outstanding(source: Installation, plan: SplitPlan) -> bool:
    """Whether the source still holds anything the plan moved."""
    recorded = planned_hashes(source)
    return bool(
        moved_files(source, plan)
        or plan.units_moved
        or any(name in recorded for name in plan.changes_moved)
    )


def _prune(directory: Path) -> None:
    """Remove `directory` and the empty directories under it; one holding a file stays."""
    if not directory.is_dir():
        return
    for path in sorted((p for p in directory.rglob("*") if p.is_dir()), reverse=True):
        if not any(path.iterdir()):
            path.rmdir()
    if not any(directory.iterdir()):
        directory.rmdir()


def remove(source: Installation, plan: SplitPlan) -> RemoveReport:
    """Remove the moved unit records and plan records, then the files (a directory only when
    empty). The records go first, then one directory at a time: the capability specs before
    any change or archive entry, because a capability moves only through the changes that
    own it and must go while they are on disk; each directory has its `tasks.md` last, and
    a directory is pruned as soon as its files are gone, so a run killed part way leaves the
    files that tell the next run what moved, and that run finishes it. A directory holding no
    file, which such a run can leave, is pruned too."""
    UnitStore(source.state_dir / "units.json").remove_units(plan.units_moved)
    recorded = planned_hashes(source)
    names = [name for name in plan.changes_moved if name in recorded]
    if names:
        update_plans(source, lambda _: dict.fromkeys(names))
    files = moved_files(source, plan)
    for directory in (
        *(source.specs_dir / "specs" / name for name in plan.specs_moved),
        *(source.changes_dir / name for name in plan.changes_moved),
        *(source.changes_dir / "archive" / name for name in plan.archive_moved),
    ):
        inside = (path for path in files if path.is_relative_to(directory))
        for path in sorted(inside, key=lambda path: (path.name == "tasks.md", path)):
            path.unlink()
        _prune(directory)
    for parent in (source.changes_dir, source.changes_dir / "archive", source.specs_dir / "specs"):
        for hollow in (p for p in parent.glob("*") if p.is_dir() and not is_populated(p)):
            if hollow.name != "archive":
                _prune(hollow)
    return RemoveReport(
        files_removed=len(files), units_removed=len(plan.units_moved), plans_removed=len(names)
    )


def still_naming(
    source: Installation,
    repo: str,
    allow_mixed: str | None = None,
    moving: Collection[str] = (),
) -> list[str]:
    """What in the source, after the removal, still names `repo`: a unit, a change or archive
    entry with a group tagged for it, one that cannot be read or classified, or a repo that
    consumes it. The entry may go only when this is empty. `moving` is the unit ids a run is
    about to remove, which do not count; `allow_mixed` is the side the run gave."""
    plan = plan_split(source, repo, None, allow_mixed)
    names = [
        f"unit {unit.id}"
        for unit in UnitStore(source.state_dir / "units.json").all()
        if unit.repo == repo and unit.id not in moving
    ]
    names += [f"change {item.name}" for item in (*plan.changes_mixed, *plan.archive_mixed)]
    names += [
        f"change {item.name}" for item in (*plan.changes_unreadable, *plan.archive_unreadable)
    ]
    names += [f"archive entry {name}" for name in plan.archive_unclassified]
    names += [
        f"repo {name}"
        for name, config in source.repos.items()
        if name != repo and repo in config.consumes
    ]
    return names
