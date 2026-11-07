"""Applying a change's `Project:` lines to the planning repo's abk.yaml (spec: project-lines).

An `add`, and the new half of a `replace`, is applied when the change is planned. A `remove`, and
the old half of a `replace`, is applied once the unit that carries the group is settling or merged,
and waits while an unfinished unit is stored in that project. Each application is recorded in a
ledger in the state folder, keyed by change, group and a hash of the line.

A failure never raises: it is logged, kept in the ledger and retried on the next run, and shown by
`abk status` and `abk doctor`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from pathlib import Path

import yaml

from agent_build_kit import config as config_module
from agent_build_kit.init.scaffold import (
    ScaffoldError,
    add_project,
    remove_project,
)
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.file_lock import LockTimeout, atomic_write_text
from agent_build_kit.pipeline.planning_commit import commit_and_publish
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import FINISHED_STATES, MERGED, SETTLING, ProjectLine
from agent_build_kit.pipeline.work_graph import (
    declared_profiles,
    declared_projects,
    declared_split_names,
    tag_path,
    validate_tasks,
)
from agent_build_kit.tracks.runner import RUN_ID

LEDGER_FILE = "project_actions.json"
CONFIG_FILE = "abk.yaml"
# The states in which the unit carrying a group has merged its code.
MERGE_REACHED = (SETTLING, MERGED)
# What reading abk.yaml or a tasks.md can raise.
_READ_ERRORS = (config_module.ConfigError, OSError, ValueError, yaml.YAMLError)


class ActionReport(Frozen):
    """What one run of the step did, as lines a person can read."""

    # Applied now, or found already applied and recorded.
    applied: tuple[str, ...] = ()
    # A `remove` held while an unfinished unit is stored in the project.
    waiting: tuple[str, ...] = ()
    # An edit that could not be made, to be retried on the next tick.
    failed: tuple[str, ...] = ()


class _Due(Frozen):
    """One half of one line, due now."""

    key: str
    change: str
    group: int
    repo: str
    line: ProjectLine
    # `add` puts a project in; `remove` takes one out.
    edit: str
    path: str

    @property
    def text(self) -> str:
        return f"{self.change} group {self.group}: {self.line.text}"


def action_key(change: str, group: int, line: ProjectLine) -> str:
    """The ledger key of one line: its change, its group and a hash of the line's text."""
    digest = hashlib.sha256(line.text.encode()).hexdigest()[:12]
    return f"{change}/{group}/{digest}"


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _ledger_path(inst: Installation) -> Path:
    return inst.state_dir / LEDGER_FILE


def _failures(ledger: dict) -> dict[str, dict]:
    return ledger.get("failed", {})


def _save(inst: Installation, ledger: dict, log: Callable[[str], None]) -> None:
    try:
        atomic_write_text(_ledger_path(inst), json.dumps(ledger, indent=2, sort_keys=True))
    except OSError as exc:
        log(f"project actions: the ledger could not be written: {exc}")


def _groups_of(inst: Installation, change: str, *, clean: bool = False) -> list:
    """The groups of a change's `tasks.md`, read against the configuration as it is on disk now.
    With `clean`, a file that has any validation error yields none: a change the planner refuses
    gets no edit."""
    tasks = inst.changes_dir / change / "tasks.md"
    if not tasks.is_file():
        return []
    written = inst.root / CONFIG_FILE
    repos = (config_module.load(written) if written.is_file() else inst.config).repos
    groups, errors = validate_tasks(
        tasks,
        repos=tuple(repos),
        projects=declared_projects(repos),
        splits=declared_split_names(repos, inst.config),
        project_profiles=declared_profiles(repos),
    )
    return [] if clean and errors else groups


def _halves(change: str, group, edits: Sequence[str]) -> list[_Due]:
    out: list[_Due] = []
    for line in group.project_lines:
        base = action_key(change, group.number, line)
        if line.action == "add":
            parts = [("add", "", line.path)]
        elif line.action == "remove":
            parts = [("remove", "", line.path)]
        else:
            parts = [("add", "#new", line.new_path), ("remove", "#old", line.path)]
        out += [
            _Due(
                key=base + suffix,
                change=change,
                group=group.number,
                repo=group.repo,
                line=line,
                edit=edit,
                path=path,
            )
            for edit, suffix, path in parts
            if edit in edits
        ]
    return out


def _carriers(units: Sequence[StoredUnit]) -> dict[tuple[str, int], list[StoredUnit]]:
    """The units that have reached the merge, by each (change, group) they build."""
    found: dict[tuple[str, int], list[StoredUnit]] = {}
    for unit in units:
        if unit.state not in MERGE_REACHED:
            continue
        for member in unit.members():
            for number in member.groups:
                found.setdefault((member.change, number), []).append(unit)
    return found


def _blocker(due: _Due, units: Sequence[StoredUnit], carriers: Sequence[StoredUnit]) -> str:
    """The id of an unfinished unit, other than the carrier, stored in the project `due` removes."""
    carrying = {unit.id for unit in carriers}
    for unit in units:
        if (
            unit.id not in carrying
            and unit.repo == due.repo
            and tag_path(unit.project) == tag_path(due.path)
            and unit.state not in FINISHED_STATES
        ):
            return unit.id
    return ""


def _removals(
    inst: Installation, units: Sequence[StoredUnit], pending: dict
) -> list[tuple[_Due, list[StoredUnit]]]:
    """The removes due: those of the groups a merged unit carries, and those the ledger holds from
    an earlier run, which outlive the change's `tasks.md` (archiving moves it). While the file
    exists it is the truth: a held remove whose line was edited or deleted is dropped from
    `pending`."""
    carriers = _carriers(units)
    out: dict[str, tuple[_Due, list[StoredUnit]]] = {}
    for change in sorted(
        {change for change, _ in carriers} | {e["change"] for e in pending.values()}
    ):
        if not (inst.changes_dir / change / "tasks.md").is_file():
            continue
        wanted: set[str] = set()
        for group in _groups_of(inst, change):
            for due in _halves(change, group, ("remove",)):
                wanted.add(due.key)
                if held := carriers.get((change, group.number)):
                    out[due.key] = (due, held)
        for key in [k for k, e in pending.items() if e["change"] == change and k not in wanted]:
            del pending[key]
    for key, entry in pending.items():
        if key not in out:
            due = _Due.model_validate({**entry, "line": ProjectLine.model_validate(entry["line"])})
            out[key] = (due, carriers.get((due.change, due.group), []))
    return list(out.values())


def apply_project_actions(
    inst: Installation,
    units: Sequence[StoredUnit],
    *,
    planning: Sequence[str] = (),
    publish: Callable[[str, int], None] | None = None,
    log: Callable[[str], None] = print,
) -> ActionReport:
    """Apply what is due: the adds of the changes in `planning` (and of any add that failed
    before), and the removes of every change whose carrying unit (joined groups included) is
    settling or merged. A remove that has come due is kept in the ledger until it is applied, so
    archiving its change does not lose it. `publish(change, group)` commits abk.yaml after an
    application. A failure, an unreadable abk.yaml included, is logged and reported, not raised."""
    ledger = _read(_ledger_path(inst))
    done: dict = ledger.setdefault("done", {})
    failed: dict = ledger.setdefault("failed", {})
    pending: dict = ledger.setdefault("pending", {})
    retried = {entry["change"] for entry in failed.values()}
    scanned = {*planning, *retried}
    due: list[tuple[_Due, list[StoredUnit]]] = []
    try:
        for change in sorted(scanned):
            for group in _groups_of(inst, change, clean=True):
                due += [(d, []) for d in _halves(change, group, ("add",))]
        removals = _removals(inst, units, pending)
    except _READ_ERRORS as exc:
        log(f"project actions: abk.yaml or tasks.md could not be read: {exc}")
        return ActionReport(failed=(f"could not read the project lines: {exc}",))
    due += removals
    for item, _ in removals:
        if item.key not in done:
            pending[item.key] = item.model_dump(mode="json")
    # A failure whose line no longer exists (edited, renumbered, archived) is not retried.
    current = {item.key for item, _ in due}
    for key in [
        k for k, entry in failed.items() if k not in current and entry["change"] in scanned
    ]:
        del failed[key]

    applied: list[str] = []
    waiting: list[str] = []
    problems: list[str] = []
    written: list[tuple[str, int]] = []
    for item, carriers in due:
        if item.key in done:
            continue
        if item.edit == "remove" and (blocker := _blocker(item, units, carriers)):
            waiting.append(f"{item.text} waits for {blocker}")
            continue
        try:
            _apply(inst, item)
        except (ScaffoldError, OSError, LockTimeout, ValueError, KeyError) as exc:
            log(f"project actions: {item.text} failed, will retry: {exc}")
            failed[item.key] = {"change": item.change, "group": item.group, "line": item.text}
            failed[item.key]["error"] = str(exc)
            problems.append(f"{item.text}: {exc}")
            continue
        done[item.key] = True
        failed.pop(item.key, None)
        pending.pop(item.key, None)
        applied.append(item.text)
        _save(inst, ledger, log)
        if (item.change, item.group) not in written:
            written.append((item.change, item.group))
    _save(inst, ledger, log)
    # One commit and one publication for each group, after all its edits are in the file: the
    # publication is labelled by change and group, and a second one under a label is rejected.
    if publish is not None:
        for change, number in written:
            publish(change, number)
    return ActionReport(applied=tuple(applied), waiting=tuple(waiting), failed=tuple(problems))


def _apply(inst: Installation, due: _Due) -> None:
    """Make one edit to the abk.yaml on disk, which does nothing when it already holds."""
    path = inst.root / CONFIG_FILE
    if due.edit == "add":
        add_project(path, due.repo, {"path": due.path, "profile": due.line.profile})
    else:
        remove_project(path, due.repo, due.path)


def status_lines(inst: Installation, units: Sequence[StoredUnit]) -> list[str]:
    """The lines `abk status` shows: a `remove` waiting for a project to empty, and an edit that
    failed."""
    ledger = _read(_ledger_path(inst))
    done = ledger.get("done", {})
    lines: list[str] = []
    try:
        removals = _removals(inst, units, ledger.get("pending", {}))
    except _READ_ERRORS:
        return failed_lines(inst)
    for item, carriers in removals:
        if item.key not in done and (blocker := _blocker(item, units, carriers)):
            lines.append(f"project removal waiting: {item.text} (unit {blocker} is stored in it)")
    return [*lines, *failed_lines(inst)]


def failed_lines(inst: Installation) -> list[str]:
    """The edits whose last try failed, for `abk doctor`."""
    return [
        f"project edit failed: {entry['line']}: {entry['error']}"
        for entry in _failures(_read(_ledger_path(inst))).values()
    ]


def commit_project_file(
    inst: Installation, change: str, group: int, *, log: Callable[[str], None] = print
) -> bool:
    """Commit abk.yaml alone to the planning repo, with a message naming the change and group.
    True when a commit was made, and published as `planning.publish` says; a refused commit is
    logged and returns False."""
    return commit_and_publish(
        inst,
        [CONFIG_FILE],
        message=f"{CONFIG_FILE}: apply the project lines of {change} group {group}",
        label=f"project-{change}-{group}-{RUN_ID}",
        body=f"abk applied the `Project:` lines of group {group} of the change `{change}`.",
        what=f"{CONFIG_FILE} for {change} group {group}",
        log=log,
    )
