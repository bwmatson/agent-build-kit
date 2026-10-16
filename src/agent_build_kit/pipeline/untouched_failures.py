"""A test that fails e2e-test on the base too: recorded, and fixed once by its own change.

A failure the base run names as failed is pre-existing: it is appended to a record, and it
gets one change that fixes it, written without a model after a preview that says whether the
change exists or would be written.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Sequence
from datetime import datetime
from typing import Any

from pydantic import model_validator

from agent_build_kit.config import BASE_GROUP, REST_SPLIT
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen, TestTier
from agent_build_kit.pipeline.e2e import E2eVerdict
from agent_build_kit.pipeline.failure_record import FailureRecord, Recorded, TestCount
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.flakes import add_needs_to_unit, next_fix_name, open_fix_change
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.work_graph import group_needs

PREFIX = "fix-failing"
CAPABILITY = "failing-tests"


class PreExisting(Recorded):
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


def preview(inst: Installation, test: str) -> Exists | Write:
    """What the ensure step would do for `test`; reads the changes directory only."""
    name, earlier = open_fix_change(inst, test, PREFIX)
    if name is not None:
        return Exists(change=name)
    return Write(name=next_fix_name(inst, test, PREFIX), earlier=earlier)


def ensure_fix(
    inst: Installation, entry: PreExisting, unit: StoredUnit, *, say: Callable[[str], None]
) -> str:
    """Make sure one open change fixes `entry.test`: say `exists: <change>`, or
    `would write: <change>` then `wrote: <change>`. Returns the change's name."""
    with file_lock(inst.state_dir / "preexisting.lock"):
        found = preview(inst, entry.test)
        say(found.line)
        if isinstance(found, Exists):
            return found.change
        _write_change(inst, found, entry, unit)
        say(f"wrote: {found.name}")
        return found.name


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


def wait_on_preexisting(
    inst: Installation,
    entry: PreExisting,
    unit: StoredUnit,
    *,
    wait: bool,
    say: Callable[[str], None],
) -> str | None:
    """Make sure one open change fixes `entry.test` and, when `wait`, give each group of
    `unit` a `Needs:` line on it. Returns the change, or None for a unit of that change
    itself, which waits on nothing."""
    fix = ensure_fix(inst, entry, unit, say=say)
    if unit.change == fix:
        return None
    if wait:
        add_needs_to_unit(inst, unit, fix, f"failing test {entry.test} on the base")
    return fix


def _write_change(inst: Installation, found: Write, entry: PreExisting, unit: StoredUnit) -> None:
    root = inst.changes_dir / found.name
    (root / "specs" / CAPABILITY).mkdir(parents=True)
    (root / "proposal.md").write_text(_proposal(inst, entry, unit, found.earlier))
    (root / "design.md").write_text(_design(entry))
    (root / "tasks.md").write_text(_tasks(entry, unit))
    (root / "specs" / CAPABILITY / "spec.md").write_text(
        _spec(entry, successor=bool(found.earlier))
    )


def _proposal(inst: Installation, entry: PreExisting, unit: StoredUnit, earlier: str) -> str:
    history = [e for e in preexisting_record(inst).entries() if e.test == entry.test]
    seen = [f"- {e.at:%Y-%m-%d %H:%M} UTC, unit {e.unit}" for e in history]
    if entry.unit not in {e.unit for e in history}:
        seen.append(f"- {entry.at:%Y-%m-%d %H:%M} UTC, unit {entry.unit} (this one)")
    again = (
        f"\nAn earlier change, `{earlier}`, fixed this test and was merged and archived; "
        "it fails on the base again.\n"
        if earlier
        else ""
    )
    split_line = (
        f"It belongs to the `{entry.split}` split's tests.\n\n" if entry.split != REST_SPLIT else ""
    )
    return (
        "## Why\n\n"
        f"`{entry.test}` fails on the base as well as on the branches that meet it, so it fails "
        "units that did not touch it.\n"
        f"{again}\n"
        f"{split_line}"
        f"It ran as `{entry.command}` and failed with `{entry.line}`. "
        f"On the base it {entry.base_result}, with this output:\n\n"
        f"```\n{entry.base_output.strip()}\n```\n\n"
        "Units that met it:\n\n" + "\n".join(seen) + "\n\n"
        "## What Changes\n\n"
        f"- `{entry.test}` passes on the base, whether the fault is in the test, the code it "
        "exercises or the environment.\n\n"
        "## Impact\n\n"
        f"- {unit.repo}: the test and, if it is at fault, the code it exercises.\n"
    )


def _design(entry: PreExisting) -> str:
    return (
        "## Context\n\n"
        f"`{entry.test}` fails on the base.\n\n"
        "## Decisions\n\n"
        "- Is the test at fault, the code it exercises, or the environment it runs in? "
        "Decide from the failure, then fix that one.\n"
    )


def _tasks(entry: PreExisting, unit: StoredUnit) -> str:
    return (
        "# Tasks\n\n"
        "Acceptance: none — the run of the fixed test under e2e-test is the check; nothing a "
        "consumer sees changes.\n\n"
        f"## 1. [{unit.repo}] [{TestTier.E2E_TEST}] Make `{entry.test}` pass on the base\n\n"
        "Priority: 1\n\n"
        "Done when the test passes on the base under the e2e-test marker.\n\n"
        f"- [ ] 1.1 Test: reproduce the failure of `{entry.test}` on the base "
        "deterministically, so it fails every time before the fix.\n"
        "- [ ] 1.2 Make the test pass: decide whether the test, the code it exercises or the "
        "environment is at fault, fix that one, and run the test alone under the e2e-test marker.\n"
    )


def _spec(entry: PreExisting, *, successor: bool) -> str:
    # The earlier attempt's archive added this requirement to the capability, and an
    # archive refuses to add one that exists: a successor restates it.
    verb = "MODIFIED" if successor else "ADDED"
    return (
        f"## {verb} Requirements\n\n"
        f"### Requirement: `{entry.test}` passes on the base\n\n"
        "The test SHALL pass on the base.\n\n"
        "#### Scenario: Run on the base\n\n"
        "- **WHEN** the test is run on the base under the e2e-test marker\n"
        "- **THEN** it passes\n"
    )
