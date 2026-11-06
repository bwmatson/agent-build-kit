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

from agent_build_kit import config as config_module
from agent_build_kit.init.scaffold import (
    ScaffoldError,
    add_project,
    remove_project,
)
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.file_lock import LockTimeout, atomic_write_text
from agent_build_kit.pipeline.shell import git
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import FINISHED_STATES, MERGED, SETTLING, ProjectLine
from agent_build_kit.pipeline.work_graph import (
    declared_profiles,
    declared_projects,
    declared_split_names,
    tag_path,
    validate_tasks,
)

LEDGER_FILE = "project_actions.json"
CONFIG_FILE = "abk.yaml"
# The states in which the unit carrying a group has merged its code.
MERGE_REACHED = (SETTLING, MERGED)


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


def _groups_of(inst: Installation, change: str) -> list:
    """The groups of a change's `tasks.md`, read against the configuration as it is on disk now."""
    tasks = inst.changes_dir / change / "tasks.md"
    if not tasks.is_file():
        return []
    written = inst.root / CONFIG_FILE
    repos = (config_module.load(written) if written.is_file() else inst.config).repos
    return validate_tasks(
        tasks,
        repos=tuple(repos),
        projects=declared_projects(repos),
        splits=declared_split_names(repos, inst.config),
        project_profiles=declared_profiles(repos),
    )[0]


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
    inst: Installation, units: Sequence[StoredUnit]
) -> list[tuple[_Due, list[StoredUnit]]]:
    carriers = _carriers(units)
    out: list[tuple[_Due, list[StoredUnit]]] = []
    for change in sorted({change for change, _ in carriers}):
        for group in _groups_of(inst, change):
            for due in _halves(change, group, ("remove",)):
                if held := carriers.get((change, group.number)):
                    out.append((due, held))
    return out


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
    settling or merged. `publish(change, group)` commits abk.yaml after an application. A failure
    is logged and reported, never raised."""
    ledger = _read(_ledger_path(inst))
    done: dict = ledger.setdefault("done", {})
    failed: dict = ledger.setdefault("failed", {})
    retried = {entry["change"] for entry in failed.values()}
    due: list[tuple[_Due, list[StoredUnit]]] = []
    for change in sorted({*planning, *retried}):
        for group in _groups_of(inst, change):
            due += [(d, []) for d in _halves(change, group, ("add",))]
    due += _removals(inst, units)

    applied: list[str] = []
    waiting: list[str] = []
    problems: list[str] = []
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
        applied.append(item.text)
        _save(inst, ledger, log)
        if publish is not None:
            publish(item.change, item.group)
    _save(inst, ledger, log)
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
    done = _read(_ledger_path(inst)).get("done", {})
    lines: list[str] = []
    for item, carriers in _removals(inst, units):
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
    True when a commit was made; a refused commit is logged and returns False."""
    staged = git(inst.root, "add", "--", CONFIG_FILE, check=False)
    if staged.returncode != 0:
        log(f"staging {CONFIG_FILE} for {change} group {group} failed:\n{staged.stderr}")
        return False
    if (
        git(inst.root, "diff", "--cached", "--quiet", "--", CONFIG_FILE, check=False).returncode
        == 0
    ):
        return False
    message = f"{CONFIG_FILE}: apply the project lines of {change} group {group}"
    committed = git(inst.root, "commit", "-q", "-m", message, "--", CONFIG_FILE, check=False)
    if committed.returncode != 0:
        log(f"committing {CONFIG_FILE} for {change} group {group} failed:\n{committed.stderr}")
        return False
    return True
