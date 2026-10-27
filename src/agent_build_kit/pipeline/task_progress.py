"""Ticking a unit's tasks off in its change's `tasks.md` — by the pipeline.

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

from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.work_graph import read_tasks

_ANY_BOX = re.compile(r"^(\s*- )\[[ xX]\]( \d+\.\d+ )", re.M)


def without_boxes(text: str) -> str:
    """`text` with every task box set to one form, so ticking is not a change to the text."""
    return _ANY_BOX.sub(r"\g<1>[ ]\g<2>", text)


def tasks_lock(tasks: Path) -> AbstractContextManager[None]:
    """The lock every write to a change's `tasks.md` and its tracker file takes: units of one
    change share the file."""
    return file_lock(tasks.with_name(f"{tasks.name}.lock"))


def mark_groups(tasks: Path, groups: Iterable[int], *, done: bool) -> None:
    """Set every task box in `groups` to done or not done.

    Only the boxes: the text is left exactly as it was. Locked, because units
    in parallel share one change's file.
    """
    numbers = "|".join(str(group) for group in groups)
    if not numbers or not tasks.exists():
        return
    box = re.compile(rf"^(\s*- )\[[ xX]\]( (?:{numbers})\.\d+ )", re.M)
    mark = "x" if done else " "
    with tasks_lock(tasks):
        text = tasks.read_text()
        updated = box.sub(rf"\g<1>[{mark}]\g<2>", text)
        if updated != text:
            tasks.write_text(updated)


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
