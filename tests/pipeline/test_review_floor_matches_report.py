"""The history floor and the report are one computation: over each table of records the floor
holds a class exactly when the report says the class does not clear the gates."""

from __future__ import annotations

import pytest

from agent_build_kit.config import AutoLandConfig
from agent_build_kit.pipeline.review_rates import class_gates
from agent_build_kit.pipeline.verdict import ClassHistory, ReviewTier, compute_verdict
from tests.review_records import by_unit, record
from tests.verdict_support import green_facts

POLICY = AutoLandConfig(min_samples=20, min_clean_rate=0.95)


def many(outcome: str, count: int, *, brief: bool = True, evidence: str = "light") -> list[dict]:
    return [record(outcome, unit_class="docs", brief=brief, evidence=evidence)] * count


def non_final() -> dict:
    return {**record("clean", unit_class="docs"), "final": False}


TABLES = {
    "none": [],
    "three-clean": many("clean", 3),
    "nineteen-clean": many("clean", 19),
    "twenty-clean": many("clean", 20),
    "twenty-clean-with-auto-evidence": many("clean", 20, evidence="auto"),
    "nineteen-clean-one-reworked": [*many("clean", 19), *many("reworked", 1)],
    "eighteen-clean-two-reworked": [*many("clean", 18), *many("reworked", 2)],
    "eighteen-clean-two-reverted": [*many("clean", 18), *many("reverted", 2)],
    "thirty-without-the-brief": many("clean", 30, brief=False),
    "nineteen-with-the-brief-and-ten-without": [
        *many("clean", 19),
        *many("clean", 10, brief=False),
    ],
    "twenty-with-the-brief-and-ten-reworked-without": [
        *many("clean", 20),
        *many("reworked", 10, brief=False),
    ],
    "open-and-closed-are-no-sample": [*many("clean", 19), *many("open", 5), *many("closed", 5)],
    "interim-records-are-no-sample": [*many("clean", 19), *[non_final()] * 5],
}


@pytest.mark.parametrize("name", sorted(TABLES))
def test_the_floor_holds_the_class_exactly_when_the_report_says_it_does_not_clear(
    name: str,
) -> None:
    records = by_unit(*TABLES[name])
    gate = class_gates(records, POLICY, {"docs"}).get("docs")
    clears = gate is not None and gate.clears

    tier = compute_verdict(green_facts(), ClassHistory.from_records(records, "docs"), POLICY).tier

    assert (tier is ReviewTier.AUTO) == clears
    assert (tier is ReviewTier.LIGHT) == (not clears)
