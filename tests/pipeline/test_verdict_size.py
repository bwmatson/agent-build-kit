"""The verdict's size step: a unit over its earned tier's buffered ceiling is held to be split
(spec: hold-and-split, a unit over its earned tier's buffered ceiling)."""

from __future__ import annotations

import subprocess

import pytest

from agent_build_kit.config import CeilingsConfig
from agent_build_kit.pipeline.verdict import (
    GroupText,
    ReviewTier,
    SplitRequest,
    TierVerdict,
    VerdictFacts,
    compute_verdict,
)
from tests.verdict_support import green_facts

AUTO, LIGHT, FULL = ReviewTier.AUTO, ReviewTier.LIGHT, ReviewTier.FULL
CEILINGS = CeilingsConfig()
BUFFER = 0.2
GROUPS = tuple(GroupText(number=n, text="task text of group " + str(n)) for n in (1, 2, 3))


def verdict(facts: VerdictFacts, ceilings: CeilingsConfig = CEILINGS) -> TierVerdict:
    return compute_verdict(facts, ceilings=ceilings, buffer=BUFFER)


def sized(
    lines: int,
    planned: ReviewTier,
    classification: ReviewTier,
    drivers: tuple[str, ...] = (),
    size_waived: bool = False,
) -> VerdictFacts:
    return green_facts(
        planned_estimate=planned,
        classification=classification,
        changed_lines=lines,
        groups=GROUPS,
        drivers=drivers,
        size_waived=size_waived,
    )


def test_a_unit_planned_auto_that_earns_full_is_held_at_950_lines() -> None:
    result = verdict(sized(950, AUTO, FULL, drivers=("group 3",)))

    assert result.tier is FULL
    assert result.split == SplitRequest(
        earned=FULL, planned=AUTO, lines=950, ceiling=750, drivers=(3,)
    )


def test_the_same_unit_is_not_held_at_800_lines() -> None:
    result = verdict(sized(800, AUTO, FULL, drivers=("group 3",)))

    assert result.tier is FULL
    assert result.split is None
    assert verdict(sized(950, AUTO, FULL, drivers=("group 3",))).split is not None


def test_the_buffered_ceiling_itself_is_not_over() -> None:
    assert verdict(sized(900, AUTO, FULL)).split is None
    assert verdict(sized(901, AUTO, FULL)).split is not None


def test_a_unit_earning_light_is_held_over_2400_and_not_at_2400() -> None:
    assert verdict(sized(2400, AUTO, LIGHT, drivers=("group 2",))).split is None

    held = verdict(sized(2401, AUTO, LIGHT, drivers=("group 2",)))

    assert held.split == SplitRequest(
        earned=LIGHT, planned=AUTO, lines=2401, ceiling=2000, drivers=(2,)
    )


def test_a_unit_planned_and_earning_light_at_2500_is_held_with_no_drivers() -> None:
    held = verdict(sized(2500, LIGHT, LIGHT))

    assert held.split == SplitRequest(earned=LIGHT, planned=LIGHT, lines=2500, ceiling=2000)


def test_a_repos_override_is_the_ceiling_used() -> None:
    roomy = CeilingsConfig(auto=5000, light=2000, full=1000)

    assert verdict(sized(1100, AUTO, FULL), roomy).split is None
    held = verdict(sized(1300, AUTO, FULL), roomy)

    assert held.split is not None
    assert held.split.ceiling == 1000


@pytest.mark.parametrize(
    ("planned", "classification", "lines"),
    [(AUTO, AUTO, 5000), (AUTO, AUTO, 100), (LIGHT, LIGHT, 2400), (FULL, FULL, 900)],
)
def test_a_unit_under_every_ceiling_keeps_its_tier_and_reason(
    planned: ReviewTier, classification: ReviewTier, lines: int
) -> None:
    facts = sized(lines, planned, classification)
    plain = compute_verdict(facts.model_copy(update={"changed_lines": None}))

    result = verdict(facts)

    assert result.split is None
    assert (result.tier, result.reason) == (plain.tier, plain.reason)
    assert verdict(sized(lines + 10000, planned, classification)).split is not None


def test_a_unit_with_no_recorded_lines_is_not_held() -> None:
    unrecorded = green_facts(planned_estimate=FULL, classification=FULL, groups=GROUPS)

    assert verdict(unrecorded).split is None
    assert verdict(unrecorded.model_copy(update={"changed_lines": 5000})).split is not None


def test_a_waived_unit_is_not_held_and_keeps_the_tier_it_earned() -> None:
    result = verdict(sized(5000, AUTO, FULL, size_waived=True))

    assert result.split is None
    assert result.tier is FULL
    assert verdict(sized(5000, AUTO, FULL)).split is not None


def test_the_result_is_the_same_on_a_second_computation() -> None:
    facts = sized(950, AUTO, FULL, drivers=("group 3",))

    assert verdict(facts) == verdict(facts)
    assert verdict(facts).split is not None


def test_the_step_starts_no_process(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("a process was started: " + repr(args))

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)

    assert verdict(sized(950, AUTO, FULL)).split is not None
