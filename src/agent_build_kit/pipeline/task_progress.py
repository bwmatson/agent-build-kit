"""Ticking a unit's tasks off in a change's tracking copy of `tasks.md` — by the pipeline.

The copy lives at `<state dir>/changes/<change>/tasks.md`, so a tick never modifies a tracked
file of the pipeline worktree. It is the repository file's text with the boxes the pipeline set,
and `reconcile` keeps it that way when a person edits the repository file.

The build agents used to tick boxes themselves as they worked, following
OpenSpec's own apply flow. That marks a group done after its first build,
before any review; when the review loop then fails it and the work is never
pushed, the file still says it was finished. Now agents may
not write to the planning repo at all (the policy hook refuses it), and a
unit's groups are ticked when it reaches `in_review` — through the build/review
loop, unit-test and the push — and unticked if it fails.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol

from agent_build_kit.config import active_local_dir
from agent_build_kit.pipeline.file_lock import change_lock, change_lock_path, file_lock
from agent_build_kit.pipeline.work_graph import read_tasks

_ANY_BOX = re.compile(r"^(\s*- )\[[ xX]\]( \d+\.\d+ )", re.M)
_TASK = re.compile(r"^(\s*- )\[([ xX])\]( (\d+)\.(\d+) )")
TASKS_FILE = "tasks.md"
PROGRESS_LOCK = "progress"


class Tracked(Protocol):
    """Where a change's files are: an `Installation` is one."""

    @property
    def state_dir(self) -> Path: ...

    @property
    def changes_dir(self) -> Path: ...

    @property
    def local_dir(self) -> Path: ...


def without_boxes(text: str) -> str:
    """`text` with every task box set to one form, so ticking is not a change to the text."""
    return _ANY_BOX.sub(r"\g<1>[ ]\g<2>", text)


def tasks_lock(tasks: Path) -> AbstractContextManager[None]:
    """The lock every write to a change's repository `tasks.md` and its tracker file takes:
    units of one change share the file. It is `change_lock(.., "tasks.md")` of the active
    installation, for a caller that holds the file's path and no installation."""
    local = active_local_dir()
    if local is None:
        return file_lock(tasks.with_name(f"{tasks.name}.lock"))
    return file_lock(change_lock_path(local, tasks.parent.name, TASKS_FILE))


def progress_root(inst: Tracked) -> Path:
    """The folder holding every change's tracking copy: `<state dir>/changes`."""
    return inst.state_dir / "changes"


def progress_dir(inst: Tracked, change: str) -> Path:
    """The folder holding `change`'s tracking copy: `<state dir>/changes/<change>`."""
    return progress_root(inst) / change


def _read(path: Path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None


def _reconciled(repository: str, copy: str) -> str:
    """`repository` with each task's box taken from `copy` by its number."""
    boxes: dict[tuple[int, int], str] = {}
    for line in copy.splitlines():
        found = _TASK.match(line)
        if found:
            boxes[int(found[4]), int(found[5])] = found[2]
    finished = {
        group
        for group in {g for g, _ in boxes}
        if all(box != " " for (g, _), box in boxes.items() if g == group)
    }
    lines = []
    for line in repository.splitlines(keepends=True):
        found = _TASK.match(line)
        if found:
            group, task = int(found[4]), int(found[5])
            if (group, task) in boxes:
                box = boxes[group, task]
            else:
                box = "x" if group in finished else " "
            line = f"{found[1]}[{box}]{found[3]}{line[found.end() :]}"
        lines.append(line)
    return "".join(lines)


def _reconcile_locked(inst: Tracked, change: str) -> None:
    # Always progress, then tasks.md: the one order any caller takes the two.
    with change_lock(inst, change, TASKS_FILE):
        repository = _read(inst.changes_dir / change / TASKS_FILE)
    if repository is None:
        return
    path = progress_dir(inst, change) / TASKS_FILE
    existing = _read(path)
    text = repository if existing is None else _reconciled(repository, existing)
    if text != existing:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def reconcile(inst: Tracked, change: str) -> None:
    """Rebuild the copy of `tasks.md` from the repository file, keeping ticks by number.

    The copy is made from the repository file, boxes included, when there is none. A
    repository file that cannot be read leaves the copy as it is, and creates none.
    """
    with change_lock(inst, change, PROGRESS_LOCK):
        _reconcile_locked(inst, change)


def mark_groups(inst: Tracked, change: str, groups: Iterable[int], *, done: bool) -> None:
    """Set every task box in `groups` to done or not done, in `change`'s copy only.

    Only the boxes: the text is left exactly as it was. Locked, because units in parallel
    share one change's copy.
    """
    numbers = "|".join(str(group) for group in groups)
    if not numbers:
        return
    box = re.compile(rf"^(\s*- )\[[ xX]\]( (?:{numbers})\.\d+ )", re.M)
    mark = "x" if done else " "
    path = progress_dir(inst, change) / TASKS_FILE
    with change_lock(inst, change, PROGRESS_LOCK):
        _reconcile_locked(inst, change)
        text = _read(path)
        if text is None:
            return
        updated = box.sub(rf"\g<1>[{mark}]\g<2>", text)
        if updated != text:
            path.write_text(updated)


class TaskConflict(ValueError):
    """A task's line no longer matches the hash recorded for it; the message names its key."""


def first_line_hash(text: str) -> str:
    """A short hash of the first line of a task's text, the form `tracker.yaml` records."""
    first = text.strip().split("\n", 1)[0].strip()
    return hashlib.sha256(first.encode()).hexdigest()[:12]


def mark_task(tasks: Path, key: str, *, done: bool, text_hash: str) -> None:
    """Set the one box of task `key` (`<change>:<group>.<task>`) to done or not done.

    Raises `TaskConflict` and writes nothing when the line's first-line hash is not `text_hash`."""
    change = key.rsplit(":", 1)[0]
    with tasks_lock(tasks):
        found = next((task for task in read_tasks(tasks, change) if task.key == key), None)
        if found is None or first_line_hash(found.text) != text_hash:
            raise TaskConflict(f"task {key} no longer matches the text recorded for it")
        lines = tasks.read_text().splitlines(keepends=True)
        mark = "x" if done else " "
        lines[found.line - 1] = re.sub(r"\[[ xX]\]", f"[{mark}]", lines[found.line - 1], count=1)
        tasks.write_text("".join(lines))
