"""A flaky test: told from a failure by running it alone, recorded, and fixed once.

When unit-test fails on tests, the failed tests are run again serially. A test that fails
again is a failure. One that passes both reruns is a flake: it is recorded, it gets one
change that makes it deterministic, and every unit that met it waits on that change. The change
is written by the regression agent (`pipeline/regression_agent.py`); this module holds the
record, the lookup of the open change for a test and the `Needs:` line.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from agent_build_kit.config import active, active_root
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.failure_record import (
    Evidenced,
    FailureRecord,
    Recorded,
    Storm,
    TestCount,
)
from agent_build_kit.pipeline.file_lock import change_lock
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import PRODUCT_DEFECT_PREFIX, Unit
from agent_build_kit.pipeline.work_graph import FIX_PREFIX, GROUP_HEADING, group_needs

# The longest a change's name gets before it is cut and given a hash of the whole.
NAME_LIMIT = 70
# What the names of changes that fixed a flaky or a failing test started with, still found.
FLAKY_PREFIX = "fix-flaky"
FAILING_PREFIX = "fix-failing"
# The names every change that fixes a failing test may start with, whatever its kind.
FIX_PREFIXES = (FIX_PREFIX, FLAKY_PREFIX, FAILING_PREFIX, PRODUCT_DEFECT_PREFIX)
# Where a module imported by a test may sit in the code repo, relative to its root.
SOURCE_ROOTS = ("", "src")
# How many of a storm's tests its row names.
STORM_TESTS = 10


class Flake(Recorded, Evidenced):
    """One test that failed under load and passed alone."""

    command: str
    output: str
    # The test's own section of the first run's output: its traceback and captured output.
    failure: str = ""
    at: datetime
    # Set by whoever records it: unit-test does not know which unit it ran for.
    unit: str = ""
    # Where unit-test ran it (a project below the repo root, or the root), which its
    # identifier is relative to; empty when unknown.
    directory: str = ""
    # Set for a test that failed and is not a flake (it fails on the base, by its time limit,
    # or has an open fix): it is said as a failing test and is not recorded as a flake.
    failing: bool = False
    # The ref the failure is judged against: the unit's own base, the branch tip of its parent
    # when it is stacked, which the agent reads. Empty when the run has no base.
    base: str = ""
    # The output of the test's run on `base`; empty when it was not run there (a failure by the
    # time limit alone cannot be told apart on the base).
    base_output: str = ""


def waiting_note(tests: list[str], *, failing: bool = False) -> str:
    """What a unit parked for these tests is waiting for, in a person's words."""
    kind = "failing" if failing else "flaky"
    return f"waiting for the fix of the {kind} test {', '.join(tests)}"


class FlakeFound(Exception):
    """Raised by unit-test when every failed test passed both serial reruns: the unit is not
    failed for them, it waits for their fix. `scoped` marks a flake met in a moved base's
    scoped run, which is recorded without the unit waiting."""

    def __init__(self, flakes: tuple[Flake, ...], *, scoped: bool = False) -> None:
        super().__init__(", ".join(flake.test for flake in flakes))
        self.flakes = flakes
        self.scoped = scoped


class FailedOnBase(Exception):
    """Raised by unit-test when a failed test the unit did not write fails alone and on the
    unit's own base too, or fails alone by its time limit: the failure is not the unit's, and
    the regression agent writes the change that fixes it."""

    def __init__(self, failures: tuple[Flake, ...]) -> None:
        super().__init__(", ".join(failure.test for failure in failures))
        self.failures = tuple(failure.model_copy(update={"failing": True}) for failure in failures)


@runtime_checkable
class OnFlake(Protocol):
    """Told the unit and a flake it met: records it and makes sure the one change that fixes
    it exists, and with `wait` has the unit wait on that change, unless it is a unit of a fix
    change, which waits on no other fix. Answers the change, or None for a unit of the
    change itself, which has nothing to wait on."""

    def __call__(self, unit: Unit, flake: Flake, *, wait: bool = True) -> str | None: ...


FlakeCount = TestCount


def flake_record(inst: Installation) -> FailureRecord[Flake]:
    return FailureRecord(inst.state_dir / "flakes.jsonl", Flake)


def record_storm(
    unit: str,
    tests: list[str],
    command: str,
    failures: list[str],
    *,
    evidence: str = "",
    ran_at: datetime | None = None,
    conditions: dict[str, object] | None = None,
) -> None:
    """Record one `storm` row for `unit`: `tests` failed a run's first pass and passed alone,
    more of them than `global_limits.max_flakes_per_run`. Names the first `STORM_TESTS` of them and
    keeps `failures`, the failure sections of the first few, and the `evidence` bundle, the
    time the run started and the `conditions` it ran under. No
    row is written when no workspace is loaded."""
    root = active_root()
    if root is None:
        return
    flake_record(Installation(active(), root)).append(
        Storm(
            unit=unit,
            at=datetime.now(UTC),
            count=len(tests),
            tests=tests[:STORM_TESTS],
            command=command,
            failures=failures,
            evidence=evidence,
            ran_at=ran_at,
            conditions=conditions or {},
        )
    )


def flake_change_name(test: str) -> str:
    """The name of the change that fixes the flaky `test`."""
    return fix_change_name(test, FIX_PREFIX)


def fix_change_name(test: str, prefix: str) -> str:
    """The name of the change that fixes `test`, from its identifier: `prefix` and
    lower-case words joined by hyphens, the same for the same test, cut with a hash of
    the whole when it is long."""
    slug = re.sub(r"[^a-z0-9]+", "-", test.lower()).strip("-")
    name = f"{prefix}-{slug}"
    if len(name) > NAME_LIMIT:
        name = f"{name[: NAME_LIMIT - 9].rstrip('-')}-{hashlib.sha1(test.encode()).hexdigest()[:8]}"
    return name


# --- which change ----------------------------------------------------------------


def _candidates(test: str, prefix: str):
    """Each attempt's names for `test`: one per prefix looked under, the one new changes take
    first. Without `prefix` the test-fix prefixes are all looked under."""
    prefixes = (prefix,) if prefix else (FIX_PREFIX, FLAKY_PREFIX, FAILING_PREFIX)
    bases = [fix_change_name(test, p) for p in prefixes]
    yield bases
    attempt = 2
    while True:
        yield [f"{base}-{attempt}" for base in bases]
        attempt += 1


def _archived(inst: Installation, name: str) -> bool:
    return any((inst.changes_dir / "archive").glob(f"*-{name}"))


def open_fix_change(inst: Installation, test: str, prefix: str = "") -> tuple[str | None, str]:
    """The open change that fixes `test` under `prefix` (any test-fix prefix when empty), or
    None and the last archived attempt (or "")."""
    earlier = ""
    for names in _candidates(test, prefix):
        for name in names:
            if (inst.changes_dir / name).is_dir():
                return name, earlier
        archived = [name for name in names if _archived(inst, name)]
        if not archived:
            return None, earlier
        earlier = archived[0]
    raise AssertionError("unreachable")


def next_fix_name(inst: Installation, test: str, prefix: str = "") -> str:
    """The name the next change for `test` gets: the first attempt with no change open or
    archived under any prefix looked under, named with `prefix` or `FIX_PREFIX`."""
    for names in _candidates(test, prefix):
        if not any((inst.changes_dir / n).exists() or _archived(inst, n) for n in names):
            return names[0]
    raise AssertionError("unreachable")


def is_fix_change(change: str) -> bool:
    """Whether `change` is a change that fixes a failing or flaky test. A unit of one waits on
    no other fix: its checks set aside what fails on the base too."""
    return change.startswith(FIX_PREFIXES)


def covered_tests(tests: list[str]) -> list[str]:
    """The `tests` that an open fix change covers, of any prefix. Empty when no workspace is
    loaded."""
    root = active_root()
    if root is None:
        return []
    inst = Installation(active(), root)
    return [test for test in tests if open_fix_change(inst, test)[0] is not None]


# --- the Needs: line -------------------------------------------------------------


def add_needs_to_unit(inst: Installation, unit: StoredUnit, fix: str, reason: str) -> None:
    """Give every group of every member of `unit` a `Needs:` line on `fix`."""
    for member in unit.members():
        for group in member.groups:
            add_needs(inst, member.change, group, fix, reason)


def add_needs(inst: Installation, change: str, group: int, fix: str, reason: str) -> None:
    """Give `group` of `change` a `Needs:` line on group 1 of `fix`, with `reason`."""
    tasks = inst.changes_dir / change / "tasks.md"
    if not tasks.is_file():
        return
    # Every writer of the repository file takes this lock: units of one change share it.
    with change_lock(inst, change, "tasks.md"):
        if any(n.change == fix for n in group_needs(tasks).get(group, [])):
            return
        lines = tasks.read_text().splitlines()
        for index, line in enumerate(lines):
            heading = GROUP_HEADING.match(line)
            if heading and int(heading["number"]) == group:
                lines[index + 1 : index + 1] = [
                    "",
                    f"Needs: {fix} group 1 — {reason}",
                ]
                tasks.write_text("\n".join(lines) + "\n")
                return


# --- what the agent is told ------------------------------------------------------


# The line of a fix change's proposal that names the failing test the change is for, and the
# pattern that reads it: what the regression agent writes in place of a group title.
FAILING_TEST_LABEL = "Failing test:"
FAILING_TEST_LINE = re.compile(
    rf"^\W*{re.escape(FAILING_TEST_LABEL)}\s*`?(?P<test>[^`\s]+)`?\s*$", re.MULTILINE
)
FIRST_ATTEMPTS = 20  # how many successive names of one test's fix change are looked under


def fix_change_test(inst: Installation, change: str) -> str | None:
    """The test the fix change `change` is for: the `Failing test:` line of its proposal, which
    the regression agent writes and its check requires; None when the change has none."""
    try:
        named = FAILING_TEST_LINE.search((inst.changes_dir / change / "proposal.md").read_text())
    except OSError:
        return None
    return named["test"] if named else None


def merged_fix_since(inst: Installation, change: str, test: str) -> str | None:
    """The archived fix change for `test`, other than `change`, archived on a day strictly
    after the day `change` was written, or None. An archive name holds only a date, so a fix
    archived the same day is not taken as newer (the change may be its own successor, written
    after that fix flaked again); the day is that of the change's proposal file, and a checkout
    that moves it later only makes the answer None."""
    for name in ("proposal.md", "tasks.md"):
        try:
            written = datetime.fromtimestamp(
                (inst.changes_dir / change / name).stat().st_mtime, UTC
            )
            break
        except OSError:
            continue
    else:
        return None
    day = f"{written:%Y-%m-%d}"
    archive = inst.changes_dir / "archive"
    for attempt, names in zip(range(FIRST_ATTEMPTS), _candidates(test, ""), strict=False):
        found = False
        for name in names:
            found = found or (inst.changes_dir / name).is_dir()
            for merged in sorted(archive.glob(f"*-{name}")):
                found = True
                if merged.name[11:] == name and name != change and merged.name[:10] > day:
                    return name
        if not found and attempt:
            break
    return None


EVIDENCE_CHARS = 1500


def reproduction_evidence(inst: Installation, test: str) -> str:
    """What the flake record holds of the first recorded failure of `test`, for a build to
    judge by: when it ran, its output and conditions, and the failing run's bundle when that
    folder exists. Empty when none is recorded."""
    for entry in flake_record(inst).entries():
        if entry.test != test:
            continue
        lines = [f"- {entry.at:%Y-%m-%d %H:%M} UTC, unit {entry.unit or 'unknown'}"]
        output = (entry.failure or entry.output).strip()
        if output:
            lines.append(output[-EVIDENCE_CHARS:])
        if entry.conditions:
            lines.append(f"conditions: {entry.conditions}")
        if entry.evidence and Path(entry.evidence).exists():
            lines.append(f"bundle of the failing run: {entry.evidence}")
        return "\n".join(lines)
    return ""
