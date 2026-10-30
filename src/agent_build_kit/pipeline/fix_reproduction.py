"""Whether the test a fix change is named for still fails, checked before its first build.

The pure part: the runs and what they add up to. The commands are `wiring.build_reproduce`."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from agent_build_kit.model import Frozen


class Attempt(StrEnum):
    """How one run of the test ended."""

    PASSED = "passed"
    FAILED = "failed"
    NOT_COLLECTED = "not_collected"


class Outcome(StrEnum):
    FAILS = "fails"
    NOT_REPRODUCED = "not_reproduced"
    GONE = "gone"
    SKIPPED = "skipped"


class Reproduction(Frozen):
    outcome: Outcome
    note: str = ""


def check(
    test: str, runs: int, *, alone: Callable[[], Attempt], loaded: Callable[[], Attempt]
) -> Reproduction:
    """Run `test` `runs` times alone and then `runs` times under load, stopping at the first
    failure (`FAILS`) or the first run that finds it is not collected (`GONE`); a test that
    passed every run is `NOT_REPRODUCED`, with the note saying how many runs of each."""
    for run in (alone, loaded):
        for _ in range(runs):
            match run():
                case Attempt.FAILED:
                    return Reproduction(outcome=Outcome.FAILS, note=f"{test} fails")
                case Attempt.NOT_COLLECTED:
                    return Reproduction(outcome=Outcome.GONE, note=gone_note(test))
                case Attempt.PASSED:
                    pass
    return Reproduction(
        outcome=Outcome.NOT_REPRODUCED,
        note=f"not reproduced: 0 of {runs} runs alone, 0 of {runs} under load",
    )


def gone_note(test: str) -> str:
    """Why a unit whose test is not collected on its base is satisfied."""
    return f"{test} is no longer in the tree"


GUIDANCE = """\
The reproduction check ran `{test}` on this unit's base and it never failed ({note}).
{evidence}
Build the change as it is written, but judge whether the cause is already gone. If it is,
make no change: write nothing, in the tests step or the implementation step (no tests, no
code, whatever the step's instructions say about new tests), and state why with a
concrete cause, such as the commit that removed the race, not only that the test passed: your
statement becomes the unit's note. If the defect is still there, fix it.
"""


def unreproduced_guidance(test: str, note: str, evidence: str) -> str:
    """The guidance a build of a unit whose test never failed is given: the counts, the
    evidence of the first failure, and the "cause already gone" answer it may give."""
    shown = f"\nEvidence of the first recorded failure:\n{evidence}\n" if evidence else ""
    return GUIDANCE.format(test=test, note=note, evidence=shown)
