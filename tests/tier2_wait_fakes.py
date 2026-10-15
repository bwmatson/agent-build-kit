"""A tier 2 that fails with a verdict, for the tests of what the node does with one."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.tier2 import TestFailure, Tier2Result, Tier2Verdict, build_snapshot
from agent_build_kit.pipeline.units import Unit

OWN = "tests/live/test_own.py::test_own"
BROKEN = "tests/far/test_broken.py::test_broken"
OLD = "tests/far/test_old.py::test_old"
OTHER_OLD = "tests/far/test_older.py::test_older"
FIX = "fix-failing-test-old"
OLD_OUTPUT = "OLD-OUTPUT-MARK the base fails this one too"
OWN_OUTPUT = "OWN-OUTPUT-MARK the unit's own test fails"
COMMAND = "uv run pytest -m local_stack -v"


def failure(test: str, group: str = "") -> TestFailure:
    return TestFailure(test=test, line="assert in " + test.rpartition("::")[2], group=group)


def snapshot_of(*tests: str, tail: str = "") -> str:
    """The snapshot of a failed tier 2 run that failed `tests`, with `tail` as its output."""
    listing = "\n".join("FAILED " + t + " - " + failure(t).line for t in tests)
    return build_snapshot(
        Tier2Result(
            sha="abcdef1234567",
            passed=3,
            failed=len(tests),
            skipped=0,
            duration_seconds=1.5,
            command=COMMAND,
            output=tail or listing,
            failures=[failure(t) for t in tests],
        )
    )


def verdict_of(
    *,
    own: tuple[str, ...] = (),
    broken: tuple[str, ...] = (),
    old: tuple[str, ...] = (),
    group: str = "",
) -> Tier2Verdict:
    return Tier2Verdict(
        own=[failure(t) for t in own],
        broken=[failure(t) for t in broken],
        pre_existing=[failure(t, group) for t in old],
        command=COMMAND,
        base_output="\n".join("FAILED " + t + " - " + failure(t).line for t in old),
    )


class Failing:
    """Tier 2 that fails with `snapshot` and `verdict` on its first `fails` runs, then passes.
    Each run is recorded in the recorder's events, as the recorder's own tier 2 does."""

    def __init__(
        self, events: list[str], snapshot: str, verdict: Tier2Verdict | None, fails: int = 1
    ) -> None:
        self.events, self.snapshot, self.fails = events, snapshot, fails
        self.runs = 0
        self._verdict = verdict
        self.verdict: Tier2Verdict | None = None
        self.asked = 0

    def run(self, *, cwd: Path, base: str | None = None) -> tuple[bool, str]:
        self.runs += 1
        self.events.append("tier2")
        if self.runs <= self.fails:
            self.verdict = self._verdict
            return False, self.snapshot
        self.verdict = None
        return True, "## Tier 2 results\nfine"

    def judged(self) -> Tier2Verdict | None:
        self.asked += 1
        return self.verdict


class Told:
    """What the runner was told of each pre-existing failure: the unit, the test and whether
    the unit waits. Answers `fix`, or None for a unit of the fix change."""

    def __init__(self, fix: str | None = FIX) -> None:
        self.fix = fix
        self.told: list[tuple[str, str, bool]] = []

    def __call__(
        self, unit: Unit, verdict: Tier2Verdict, failure: TestFailure, *, wait: bool
    ) -> str | None:
        self.told.append((unit.id, failure.test, wait))
        return self.fix
