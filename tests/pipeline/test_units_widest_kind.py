"""A unit built from several groups takes the widest of their kinds."""

from __future__ import annotations

import itertools

import pytest

from agent_build_kit.pipeline.units import plan_units

UNIT, INTEGRATION, E2E = "unit-test", "integration-test", "e2e-test"


def kind_of_unit_built_from(*kinds: str) -> str:
    groups = [
        dict(number=n, repo="app", tier=kind, title=f"group {n}", estimated_lines=100)
        for n, kind in enumerate(kinds, start=1)
    ]
    (built,) = plan_units("feature", groups, min_lines=1000, max_lines=2000)
    return built.tier


@pytest.mark.parametrize(
    ("kinds", "widest"),
    [
        ((UNIT, INTEGRATION), INTEGRATION),
        ((INTEGRATION, INTEGRATION), INTEGRATION),
    ],
)
def test_a_unit_takes_the_widest_kind_whatever_the_order_of_its_groups(
    kinds: tuple[str, ...], widest: str
) -> None:
    for order in itertools.permutations(kinds):
        assert kind_of_unit_built_from(*order) == widest


def test_an_e2e_test_group_makes_the_unit_e2e_test_beside_any_other_kind() -> None:
    for order in itertools.permutations((UNIT, INTEGRATION, E2E)):
        assert kind_of_unit_built_from(*order) == E2E
    for order in itertools.permutations((INTEGRATION, E2E)):
        assert kind_of_unit_built_from(*order) == E2E
    assert kind_of_unit_built_from(INTEGRATION) == INTEGRATION
