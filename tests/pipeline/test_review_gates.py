"""A class clears the gates on its own record; one no policy names is marked not nameable."""

from __future__ import annotations

from agent_build_kit.config import AutoLandConfig
from agent_build_kit.pipeline.review_rates import class_gates

POLICY = AutoLandConfig(min_samples=20, min_clean_rate=0.95)


def records(clean: int, reworked: int = 0, unit_class: str = "docs") -> dict[str, dict]:
    outcomes = ["clean"] * clean + ["reworked"] * reworked
    return {
        "feature/" + str(n): {
            "final": True,
            "unit_class": unit_class,
            "brief": True,
            "outcome": outcome,
            "evidence_tier": "light",
        }
        for n, outcome in enumerate(outcomes, start=1)
    }


def test_twenty_samples_with_nineteen_clean_clear_the_gates() -> None:
    gate = class_gates(records(19, 1), POLICY, {"docs"})["docs"]
    assert gate.clears
    assert gate.more_samples == 0


def test_nineteen_clean_samples_do_not_clear_and_the_shortfall_is_named() -> None:
    gate = class_gates(records(19), POLICY, {"docs"})["docs"]
    assert not gate.clears
    assert gate.more_samples == 1


def test_twenty_samples_with_eighteen_clean_do_not_clear() -> None:
    gate = class_gates(records(18, 2), POLICY, {"docs"})["docs"]
    assert not gate.clears
    assert gate.more_samples == 0


def test_a_named_class_is_nameable() -> None:
    assert class_gates(records(20), POLICY, {"docs"})["docs"].nameable


def test_a_class_no_policy_names_is_not_nameable_even_when_it_clears() -> None:
    gate = class_gates(records(20, unit_class="app/unit-test"), POLICY, {"docs"})["app/unit-test"]
    assert gate.clears
    assert not gate.nameable
