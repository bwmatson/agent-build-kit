"""No floor lowers another, and the verdict is repeatable
(spec: review-verdict, deterministic verdict).

Each test loops over its combinations, so a failure names the one that did it."""

from __future__ import annotations

import itertools
from typing import Any, NamedTuple

from agent_build_kit.pipeline.verdict import (
    ClassHistory,
    GateResult,
    ReviewTier,
    compute_verdict,
)
from tests.verdict_support import green_facts

AUTO, LIGHT, FULL = ReviewTier.AUTO, ReviewTier.LIGHT, ReviewTier.FULL
_RANK = list(ReviewTier)
PROVEN = ClassHistory(samples=20, clean=20)


class Floor(NamedTuple):
    name: str
    tier: ReviewTier
    changes: dict[str, Any]
    history: ClassHistory = PROVEN


FLOORS = [
    Floor("estimate-light", LIGHT, {"planned_estimate": LIGHT}),
    Floor("estimate-full", FULL, {"planned_estimate": FULL}),
    Floor("protected-path", FULL, {"protected_paths": ("Dockerfile",)}),
    Floor("flag", FULL, {"flags": ("contract",)}),
    Floor("red-first-missing", FULL, {"red_first": GateResult.MISSING}),
    Floor("unit-test-failed", FULL, {"unit_test": GateResult.FAILED}),
    Floor("open-finding", FULL, {"open_required_findings": 1}),
    Floor("classified-light", LIGHT, {"classification": LIGHT}),
    Floor("classified-full", FULL, {"classification": FULL}),
    Floor("no-classification", FULL, {"classification": None}),
    Floor("thin-history", LIGHT, {}, ClassHistory(samples=1, clean=1)),
]


def _rank(tier: ReviewTier) -> int:
    return _RANK.index(tier)


def _verdict(*floors: Floor) -> ReviewTier:
    changes: dict[str, Any] = {}
    for floor in floors:
        changes.update(floor.changes)
    history = min((f.history for f in floors), key=lambda h: h.samples)
    return compute_verdict(green_facts(**changes), history).tier


def test_each_floor_alone_gives_its_tier() -> None:
    for floor in FLOORS:
        assert _verdict(floor) is floor.tier, floor.name


def test_two_floors_give_at_least_the_higher_and_the_same_answer_twice() -> None:
    for first, second in itertools.combinations(FLOORS, 2):
        if set(first.changes) & set(second.changes):
            continue  # two values of one field are one floor, not two
        got = _verdict(first, second)
        assert _rank(got) >= max(_rank(first.tier), _rank(second.tier)), (first.name, second.name)
        assert _verdict(first, second) == got, (first.name, second.name)


def test_a_lower_classification_never_lowers_a_higher_floor() -> None:
    higher = [f for f in FLOORS if f.tier is FULL and "classification" not in f.changes]
    for floor in higher:
        for classification in (AUTO, LIGHT, None):
            changes = {**floor.changes, "classification": classification}
            verdict = compute_verdict(green_facts(**changes), floor.history)
            assert verdict.tier is FULL, (floor.name, classification)
            assert verdict.evidence_tier is FULL, (floor.name, classification)
