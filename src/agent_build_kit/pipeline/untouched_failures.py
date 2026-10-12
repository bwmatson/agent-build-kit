"""A test that fails tier 2 on the base too: recorded, and fixed once by its own change.

A failure the base run names as failed is pre-existing: it is appended to a record, and it
gets one change that fixes it, written without a model after a preview that says whether the
change exists or would be written.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.flakes import _next_name, _open_change
from agent_build_kit.pipeline.unit_store import StoredUnit

PREFIX = "fix-failing"
CAPABILITY = "failing-tests"


class PreExisting(Frozen):
    """One test that failed tier 2 for a unit and failed on the base as well."""

    test: str
    unit: str
    command: str
    line: str
    at: datetime
    base_result: str = "failed"
    base_output: str = ""
    change: str = ""


class PreExistingCount(Frozen):
    """A pre-existing failing test, how many times it failed on the base and its fix change."""

    test: str
    count: int
    change: str


class PreExistingRecord:
    """The pre-existing failures found, appended to a file in the state directory."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, entry: PreExisting) -> None:
        with file_lock(self.path.with_suffix(".lock")):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(entry.model_dump_json() + "\n")

    def entries(self) -> list[PreExisting]:
        """Every failure recorded, oldest first."""
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        return [PreExisting.model_validate_json(line) for line in lines if line.strip()]

    def counts(self) -> list[PreExistingCount]:
        """Each test once, with how often it failed on the base and its latest fix change."""
        counted: dict[str, PreExistingCount] = {}
        for entry in self.entries():
            before = counted.get(entry.test)
            counted[entry.test] = PreExistingCount(
                test=entry.test,
                count=(before.count if before else 0) + 1,
                change=entry.change or (before.change if before else ""),
            )
        return list(counted.values())


def preexisting_record(inst: Installation) -> PreExistingRecord:
    return PreExistingRecord(inst.state_dir / "preexisting-failures.jsonl")


class Exists(Frozen):
    """The open change that already fixes a test."""

    change: str


class Write(Frozen):
    """The change that would be written for a test, and the archived attempt before it."""

    name: str
    earlier: str = ""


def preview(inst: Installation, test: str) -> Exists | Write:
    """What the ensure step would do for `test`; reads the changes directory only."""
    name, earlier = _open_change(inst, test, PREFIX)
    if name is not None:
        return Exists(change=name)
    return Write(name=_next_name(inst, test, PREFIX), earlier=earlier)


def ensure_fix(
    inst: Installation, entry: PreExisting, unit: StoredUnit, *, say: Callable[[str], None]
) -> str:
    """Make sure one open change fixes `entry.test`: say `exists: <change>`, or
    `would write: <change>` then `wrote: <change>`. Returns the change's name."""
    with file_lock(inst.state_dir / "preexisting.lock"):
        found = preview(inst, entry.test)
        if isinstance(found, Exists):
            say(f"exists: {found.change}")
            return found.change
        say(f"would write: {found.name}")
        _write_change(inst, found, entry, unit)
        say(f"wrote: {found.name}")
        return found.name


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
    return (
        "## Why\n\n"
        f"`{entry.test}` fails on the base as well as on the branches that meet it, so it fails "
        "units that did not touch it.\n"
        f"{again}\n"
        f"It ran as `{entry.command}` and failed with `{entry.line}`. The base run's output:\n\n"
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
        "Acceptance: none — the run of the fixed test under tier 2 is the check; nothing a "
        "consumer sees changes.\n\n"
        f"## 1. [{unit.repo}] [tier2] Make `{entry.test}` pass on the base\n\n"
        "Priority: 1\n\n"
        "Done when the test passes on the base under the tier 2 marker.\n\n"
        f"- [ ] 1.1 Test: reproduce the failure of `{entry.test}` on the base "
        "deterministically, so it fails every time before the fix.\n"
        "- [ ] 1.2 Make the test pass: decide whether the test, the code it exercises or the "
        "environment is at fault, fix that one, and run the test alone under the tier 2 marker.\n"
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
        "- **WHEN** the test is run on the base under the tier 2 marker\n"
        "- **THEN** it passes\n"
    )
