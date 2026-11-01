"""A test that fails e2e-test on the base too: recorded, and fixed once by its own change.

A failure the base run names as failed is pre-existing: it is appended to a record, and the
regression agent writes the one change that fixes it (`pipeline/regression_agent.py`). The
preview here says whether that change exists or would be written, and the helpers that
look up and write a fix change are shared with the other kinds of fix.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import model_validator

from agent_build_kit.config import BASE_GROUP, REST_SPLIT
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.e2e import E2eVerdict
from agent_build_kit.pipeline.failure_record import Evidenced, FailureRecord, Recorded, TestCount
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.flakes import (
    FIX_PREFIX,
    add_needs_to_unit,
    next_fix_name,
    open_fix_change,
)
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.work_graph import group_needs

PREFIX = FIX_PREFIX


class PreExisting(Recorded, Evidenced):
    """One test that failed e2e-test for a unit and failed on the base as well."""

    unit: str
    command: str
    line: str
    at: datetime
    base_result: str = "failed"
    base_output: str = ""
    split: str = REST_SPLIT

    @model_validator(mode="before")
    @classmethod
    def _read_older_runtime(cls, data: Any) -> Any:
        """An entry written before splits named its group `runtime`, `base` for the untagged."""
        if isinstance(data, dict) and "runtime" in data:
            data = dict(data)
            older = data.pop("runtime")
            if "split" not in data:
                data["split"] = REST_SPLIT if older == BASE_GROUP else older
        return data


PreExistingCount = TestCount


def preexisting_record(inst: Installation) -> FailureRecord[PreExisting]:
    return FailureRecord(inst.state_dir / "preexisting-failures.jsonl", PreExisting)


class Exists(Frozen):
    """The open change that already fixes a test."""

    change: str

    @property
    def line(self) -> str:
        """What the ensure step and the dry run both report."""
        return f"exists: {self.change}"


class Write(Frozen):
    """The change that would be written for a test, and the archived attempt before it."""

    name: str
    earlier: str = ""

    @property
    def line(self) -> str:
        """What the ensure step and the dry run both report."""
        return f"would write: {self.name}"


def preview_fix(inst: Installation, test: str, prefix: str) -> Exists | Write:
    """What the ensure step would do for `test` under `prefix`; reads the changes directory only."""
    name, earlier = open_fix_change(inst, test, prefix)
    if name is not None:
        return Exists(change=name)
    return Write(name=next_fix_name(inst, test, prefix), earlier=earlier)


def preview(inst: Installation, test: str) -> Exists | Write:
    """What the ensure step would do for `test`; reads the changes directory only."""
    return preview_fix(inst, test, "")


def ensure_fix_change(
    inst: Installation,
    test: str,
    prefix: str,
    *,
    lock: Path,
    write: Callable[[Write], None],
    say: Callable[[str], None],
) -> str:
    """Make sure one open change under `prefix` fixes `test`, looked up and written under `lock`:
    say `exists: <change>`, or `would write: <change>`, call `write`, and say `wrote: <change>`.
    Returns the change's name."""
    with file_lock(lock):
        found = preview_fix(inst, test, prefix)
        say(found.line)
        if isinstance(found, Exists):
            return found.change
        write(found)
        say(f"wrote: {found.name}")
        return found.name


def write_fix_change(
    root: Path, capability: str, *, proposal: str, design: str, tasks: str, spec: str
) -> None:
    """The four files of a fix change, written under `root`."""
    (root / "specs" / capability).mkdir(parents=True)
    (root / "proposal.md").write_text(proposal)
    (root / "design.md").write_text(design)
    (root / "tasks.md").write_text(tasks)
    (root / "specs" / capability / "spec.md").write_text(spec)


def wait_on_change(
    inst: Installation, unit: StoredUnit, fix: str, reason: str, *, wait: bool = True
) -> str | None:
    """With `wait`, give each group of `unit` a `Needs:` line on `fix`. Returns `fix`, or None
    for a unit of that change itself, which waits on nothing."""
    if unit.change == fix:
        return None
    if wait:
        add_needs_to_unit(inst, unit, fix, reason)
    return fix


def waiting_note(tests: list[str]) -> str:
    """What a unit parked for these failing tests is waiting for, in a person's words."""
    return f"waiting for the fix of the failing test {', '.join(tests)} on the base"


def feedback_snapshot(snapshot: str, verdict: E2eVerdict | None) -> str:
    """The snapshot of a failed run as the agent is given it: without the lines and the
    output of tests that fail on the base too, which are named once as recorded. Output is
    one cut tail for every test, so the whole block is dropped whenever a pre-existing test
    failed, the unit's own tests' output with it; their failure lines stay."""
    if verdict is None or not verdict.pre_existing:
        return snapshot
    old = [failure.test for failure in verdict.pre_existing]
    lines = [
        line
        for line in snapshot.splitlines()
        if not any(line.startswith(f"  - `{test}` -") for test in old)
    ]
    text = re.sub(r"<details>.*?</details>\n?", "", "\n".join(lines), flags=re.DOTALL)
    return f"{text.rstrip()}\n\nalso failing on the base, recorded: {', '.join(old)}\n"


def holding_fixes(
    inst: Installation,
    unit: StoredUnit,
    units: Sequence[StoredUnit],
    *,
    splits: Collection[str] | None = None,
) -> list[PreExisting]:
    """The recorded entries whose fix change is open, was recorded for `unit`'s repo
    (by the repo of the unit named in `units`), is not `unit`'s own change and has no
    `Needs:` line from `unit`, and whose split is among `splits` (None: any), the
    splits the run executes: each holds `unit` before a full e2e-test run."""
    repo_of = {other.id: other.repo for other in units}
    waits_on = {
        need.change
        for member in unit.members()
        if (tasks := inst.changes_dir / member.change / "tasks.md").is_file()
        for group in member.groups
        for need in group_needs(tasks).get(group, [])
    }
    holding: dict[str, PreExisting] = {}
    for entry in preexisting_record(inst).latest_with_change().values():
        if (
            repo_of.get(entry.unit) == unit.repo
            and (splits is None or entry.split in splits)
            and entry.change != unit.change
            and entry.change not in waits_on
            and (inst.changes_dir / entry.change).is_dir()
        ):
            holding.setdefault(entry.change, entry)
    return list(holding.values())
