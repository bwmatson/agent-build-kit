"""Whether the test a fix change is named for still fails, checked before its first build."""

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
    raise NotImplementedError
