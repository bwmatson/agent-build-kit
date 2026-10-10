"""What a run replayed and what went live, per test and in total."""

from __future__ import annotations

from agent_build_kit.model import Frozen
from agent_build_kit.replay.models import Rule


class Miss(Frozen):
    """A call that went live: its place in the test, its key, and where its request
    differs from the nearest earlier cassette for the same test and call index."""

    call_index: int
    key: str
    difference: str


class ReplayedTest(Frozen):
    test_id: str
    # The calls answered from a cassette.
    hits: int = 0
    misses: list[Miss] = []
    # The cassettes the test did not ask for, by path under the cassette directory.
    unused: list[str] = []
    # The keys of the cassettes that matched but were too old to answer.
    aged_out: list[str] = []
    rules: list[Rule] = []


class RunReport(Frozen):
    tests: list[ReplayedTest] = []
    rules: list[Rule] = []
    # The replayed calls whose recorded response carried usage figures, and those figures' total.
    billed_calls_avoided: int = 0
    tokens_avoided: int = 0


def replay_label(test: ReplayedTest) -> str | None:
    """`replayed: N of M external calls replayed, K live`, or None when nothing replayed."""
    raise NotImplementedError
