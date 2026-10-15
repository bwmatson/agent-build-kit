"""What a split moves, what stays, and what is mixed, read from the source's working tree."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Collection, Sequence
from enum import StrEnum
from pathlib import Path

from agent_build_kit.config import CONFIG_FILENAME, ConfigError, load
from agent_build_kit.init.scaffold import rules_version
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.shell import porcelain
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import HELD, IN_FLIGHT
from agent_build_kit.pipeline.work_graph import (
    ANY_GROUP_HEADING,
    TaskGroup,
    ValidationError,
    declared_projects,
    tag_path,
    validate_tasks,
)

# A held unit also blocks a split: its worktree and thread belong to the source.
UNSETTLED = (*IN_FLIGHT, HELD)

# An archive entry is the change's name after the date it was archived on.
_ARCHIVE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}-")


class SplitUsageError(ValueError):
    """The selection names something the source does not have, or a value that is no side."""


class RefusalKind(StrEnum):
    MIXED = "mixed"
    DESTINATION_LACKS_REPO = "destination-lacks-repo"
    SPANNING_UNIT = "spanning-unit"
    IN_FLIGHT_UNIT = "in-flight-unit"


class Refusal(Frozen):
    kind: RefusalKind
    line: str


class GroupSide(Frozen):
    """One group of a change: its number and the repo and project its heading tags."""

    number: int
    repo: str
    project: str


class MixedChange(Frozen):
    name: str
    groups: tuple[GroupSide, ...]


class Unreadable(Frozen):
    """A `tasks.md` that failed to read: the change or archive entry, the line and the message."""

    name: str
    line: int
    message: str


class SplitPlan(Frozen):
    repo: str
    project: str | None = None
    changes_moved: tuple[str, ...] = ()
    changes_staying: tuple[str, ...] = ()
    changes_mixed: tuple[MixedChange, ...] = ()
    changes_unreadable: tuple[Unreadable, ...] = ()
    archive_moved: tuple[str, ...] = ()
    archive_staying: tuple[str, ...] = ()
    archive_mixed: tuple[MixedChange, ...] = ()
    archive_unclassified: tuple[str, ...] = ()
    archive_unreadable: tuple[Unreadable, ...] = ()
    specs_moved: tuple[str, ...] = ()
    specs_shared: tuple[str, ...] = ()
    specs_unowned: tuple[str, ...] = ()
    units_moved: tuple[str, ...] = ()
    units_blocking: tuple[str, ...] = ()
    # `M path`, `?? path` and `D path` lines; None when the source is not under git.
    uncommitted: tuple[str, ...] | None = None
    refusals: tuple[Refusal, ...] = ()


class _Classified(Frozen):
    moved: tuple[str, ...] = ()
    staying: tuple[str, ...] = ()
    mixed: tuple[MixedChange, ...] = ()
    unreadable: tuple[Unreadable, ...] = ()
    unclassified: tuple[str, ...] = ()


def _subdirectories(parent: Path) -> list[Path]:
    if not parent.is_dir():
        return []
    return sorted(p for p in parent.iterdir() if is_populated(p) and p.name != "archive")


def is_populated(directory: Path) -> bool:
    """Whether `directory` holds a file anywhere under it; one with only empty
    subdirectories (what an interrupted removal leaves) is nothing."""
    return directory.is_dir() and any(p.is_file() for p in directory.rglob("*"))


def _checked_project(
    source: Installation, repo: str, project: str | None, declared: dict[str, tuple[str, ...]]
) -> str | None:
    if repo not in source.repos:
        known = ", ".join(source.repos)
        raise SplitUsageError(f"{repo!r} is not a repo in abk.yaml (known: {known})")
    if project is None:
        return None
    wanted = tag_path(project)
    if wanted not in declared[repo]:
        raise SplitUsageError(
            f"project {project!r} is not declared for repo {repo!r}; "
            f"it declares {', '.join(declared[repo]) or 'only its root project'}"
        )
    return wanted


def _classify(
    directories: list[Path],
    source: Installation,
    declared: dict[str, tuple[str, ...]],
    repo: str,
    project: str | None,
) -> _Classified:
    moved: list[str] = []
    staying: list[str] = []
    mixed: list[MixedChange] = []
    unreadable: list[Unreadable] = []
    unclassified: list[str] = []
    for directory in directories:
        tasks = directory / "tasks.md"
        if not tasks.is_file():
            unclassified.append(directory.name)
            continue
        groups, errors = validate_tasks(tasks, repos=tuple(source.repos), projects=declared)
        if bad := _unparsed_heading(tasks, groups, errors):
            unreadable.append(Unreadable(name=directory.name, line=bad[0], message=bad[1]))
            continue
        chosen = [_selected(group, repo, project) for group in groups]
        if groups and all(chosen):
            moved.append(directory.name)
        elif any(chosen) or (project is not None and any(g.repo == repo for g in groups)):
            sides = tuple(
                GroupSide(number=g.number, repo=g.repo, project=g.project) for g in groups
            )
            mixed.append(MixedChange(name=directory.name, groups=sides))
        else:
            staying.append(directory.name)
    return _Classified(
        moved=tuple(moved),
        staying=tuple(staying),
        mixed=tuple(mixed),
        unreadable=tuple(unreadable),
        unclassified=tuple(unclassified),
    )


def _unparsed_heading(
    tasks: Path, groups: list[TaskGroup], errors: list[ValidationError]
) -> tuple[int, str] | None:
    """The line and message of the first `## ` heading no group came from: a file with one
    cannot be classified. Other errors (a missing acceptance group) leave the groups readable."""
    parsed = {group.line for group in groups}
    for number, text in enumerate(tasks.read_text().splitlines(), start=1):
        if ANY_GROUP_HEADING.match(text) and number not in parsed:
            said = [e.message for e in errors if e.line == number]
            return number, said[0] if said else "heading is not `## N. [repo] [tier] title`"
    return None


def _selected(group: TaskGroup, repo: str, project: str | None) -> bool:
    return group.repo == repo and (project is None or group.project == project)


def _mixed_decision(
    mixed: tuple[MixedChange, ...],
    allow_mixed: str | None,
    destination_repos: Collection[str] | None,
    refused: Collection[str] = (),
) -> tuple[list[str], list[Refusal]]:
    """The mixed changes that move, and what refuses the others. An archive entry named for a
    change in `refused` is not refused again for want of a side: that change already is."""
    moving: list[str] = []
    refusals: list[Refusal] = []
    for item in mixed:
        repos = sorted({group.repo for group in item.groups})
        if allow_mixed is None:
            if _ARCHIVE_DATE.sub("", item.name) in refused:
                continue
            refusals.append(
                Refusal(
                    kind=RefusalKind.MIXED,
                    line=f"change {item.name} is mixed (groups for {', '.join(repos)}): "
                    "name a side with --allow-mixed source or destination",
                )
            )
        elif allow_mixed == "destination":
            lacking = [
                r for r in repos if destination_repos is not None and r not in destination_repos
            ]
            refusals += [
                Refusal(
                    kind=RefusalKind.DESTINATION_LACKS_REPO,
                    line=f"change {item.name} has a group for repo {name}, "
                    "which the destination does not declare",
                )
                for name in lacking
            ]
            if not lacking:
                moving.append(item.name)
    return moving, refusals


def plan_split(
    source: Installation,
    repo: str,
    project: str | None = None,
    allow_mixed: str | None = None,
    specs: Sequence[str] = (),
    *,
    destination_repos: Collection[str] | None = None,
) -> SplitPlan:
    """What moving `repo` (or its `project`) out of `source` would move, leave and refuse."""
    declared = declared_projects(source.repos)
    wanted = _checked_project(source, repo, project, declared)
    if allow_mixed not in (None, "source", "destination"):
        raise SplitUsageError(f"--allow-mixed takes `source` or `destination`, not {allow_mixed!r}")
    capabilities = {path.name for path in _subdirectories(source.specs_dir / "specs")}
    if unknown := sorted(set(specs) - capabilities):
        raise SplitUsageError(f"not a capability of the source: {', '.join(unknown)}")

    active = _subdirectories(source.changes_dir)
    archived = _subdirectories(source.changes_dir / "archive")
    changes = _classify(active, source, declared, repo, wanted)
    archive = _classify(archived, source, declared, repo, wanted)

    moving_changes, refusals = _mixed_decision(changes.mixed, allow_mixed, destination_repos)
    moving_entries, entry_refusals = _mixed_decision(
        archive.mixed, allow_mixed, destination_repos, {item.name for item in changes.mixed}
    )
    refusals += entry_refusals
    changes_moved = tuple(sorted((*changes.moved, *moving_changes)))
    archive_moved = tuple(sorted((*archive.moved, *moving_entries)))

    specs_moved, specs_shared, specs_unowned = _classify_specs(
        capabilities, (*active, *archived), {*changes_moved, *archive_moved}, set(specs)
    )
    units_moved, units_blocking, unit_refusals = _units(source, set(changes_moved))

    return SplitPlan(
        repo=repo,
        project=wanted,
        changes_moved=changes_moved,
        changes_staying=changes.staying,
        changes_mixed=changes.mixed,
        changes_unreadable=changes.unreadable,
        archive_moved=archive_moved,
        archive_staying=archive.staying,
        archive_mixed=archive.mixed,
        archive_unclassified=archive.unclassified,
        archive_unreadable=archive.unreadable,
        specs_moved=specs_moved,
        specs_shared=specs_shared,
        specs_unowned=specs_unowned,
        units_moved=units_moved,
        units_blocking=units_blocking,
        uncommitted=uncommitted(source),
        refusals=(*refusals, *unit_refusals),
    )


def _classify_specs(
    capabilities: set[str], changes: Collection[Path], moved: set[str], named: set[str]
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    owners: dict[str, list[str]] = {name: [] for name in capabilities}
    for directory in changes:
        for delta in _subdirectories(directory / "specs"):
            if delta.name in owners:
                owners[delta.name].append(directory.name)
    moving = {c for c, names in owners.items() if names and all(n in moved for n in names)}
    shared = {c for c, names in owners.items() if any(n in moved for n in names)} - moving
    unowned = {c for c, names in owners.items() if not names}
    return (
        tuple(sorted(moving | named)),
        tuple(sorted(shared - named)),
        tuple(sorted(unowned - named)),
    )


def _units(
    source: Installation, moved_changes: set[str]
) -> tuple[tuple[str, ...], tuple[str, ...], list[Refusal]]:
    moved: list[str] = []
    blocking: list[str] = []
    refusals: list[Refusal] = []
    for unit in UnitStore(source.state_dir / "units.json").all():
        changes = [member.change for member in unit.members()]
        moves = [name for name in changes if name in moved_changes]
        stays = [name for name in changes if name not in moved_changes]
        if not moves:
            continue
        if stays:
            blocking.append(unit.id)
            line = (
                f"unit {unit.id} builds change {moves[0]}, which moves, and {stays[0]}, which stays"
            )
            refusals.append(Refusal(kind=RefusalKind.SPANNING_UNIT, line=line))
        elif unit.state in UNSETTLED:
            blocking.append(unit.id)
            line = f"unit {unit.id} is {unit.state}: settle it and run again"
            refusals.append(Refusal(kind=RefusalKind.IN_FLIGHT_UNIT, line=line))
        else:
            moved.append(unit.id)
    return tuple(sorted(moved)), tuple(sorted(blocking)), refusals


def uncommitted(source: Installation) -> tuple[str, ...] | None:
    """The files under the specs and state directories git reports as modified, untracked or
    deleted, as `M path`, `?? path` and `D path`; None when the source is not under git."""
    paths = [
        str(path.relative_to(source.root))
        for path in (source.specs_dir, source.state_dir)
        if path.is_relative_to(source.root)
    ]
    if not paths:
        return ()
    try:
        entries = porcelain(source.root, *paths)
    except subprocess.CalledProcessError:
        return None
    return tuple(
        f"{'??' if code == '??' else 'D' if 'D' in code else 'M'} {path}" for code, path in entries
    )


def moved_records(source: Installation, plan: SplitPlan) -> list[StoredUnit]:
    """The source's unit records the plan moves."""
    return [
        unit
        for unit in UnitStore(source.state_dir / "units.json").all()
        if unit.id in plan.units_moved
    ]


def moved_files(source: Installation, plan: SplitPlan) -> list[Path]:
    """Every file a split copies, in path order: the moved changes, archive entries and specs
    as they are in the working tree. Lock files are not copied."""
    directories = [
        *(source.changes_dir / name for name in plan.changes_moved),
        *(source.changes_dir / "archive" / name for name in plan.archive_moved),
        *(source.specs_dir / "specs" / name for name in plan.specs_moved),
    ]
    return sorted(
        path
        for directory in directories
        for path in directory.rglob("*")
        if path.is_file() and path.suffix != ".lock"
    )


def load_destination(directory: Path, source: Installation) -> Installation:
    """The installation at `directory`, which must already exist: an `abk.yaml` that loads, a
    specs `config.yaml` with the rules stamp and a state directory. Never created here, and
    not made the active installation; raises `SplitUsageError` naming what is missing."""
    if directory.resolve() == source.root.resolve():
        raise SplitUsageError(f"the destination {directory} is the source")
    config = directory / CONFIG_FILENAME
    if not config.is_file():
        raise SplitUsageError(
            f"{config} does not exist: {directory} is not an installation; "
            f"`abk init {directory}` creates one"
        )
    try:
        destination = Installation(load(config), directory)
    except ConfigError as error:
        raise SplitUsageError(f"{config} does not load: {error}") from error
    rules = destination.specs_dir / "config.yaml"
    if not rules.is_file() or rules_version(rules.read_text()) is None:
        raise SplitUsageError(
            f"{rules} is missing or carries no `# abk-rules:` stamp; "
            f"`abk init {directory}` writes it"
        )
    if not destination.state_dir.is_dir():
        raise SplitUsageError(
            f"the state directory {destination.state_dir} does not exist; "
            f"`abk init {directory}` creates it"
        )
    return destination
