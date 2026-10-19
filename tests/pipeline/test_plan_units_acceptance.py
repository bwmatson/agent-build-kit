"""`plan_units` gives an acceptance or narrow unit the tail of its chain and every independent
unit, not every unit: the rest are reached through the chain and waited for by
`earlier_units`."""

from __future__ import annotations

from agent_build_kit.pipeline.units import plan_units


def group(number: int, **kw) -> dict:
    return {
        "number": number,
        "repo": "app",
        "tier": "unit-test",
        "title": f"group {number}",
        "estimated_lines": 200,
        "fans_out": False,
        **kw,
    }


def plan(*groups: dict):
    return plan_units("feature", list(groups), min_lines=100, max_lines=1000)


def test_an_acceptance_unit_depends_on_the_tail_and_the_independent_unit_only() -> None:
    units = plan(
        group(1),
        group(2),
        group(3),
        group(4, independent=True, repo="platform"),
        group(5, flag="acceptance", tier="e2e-test"),
    )

    assert [u.id for u in units] == [f"feature/{n}" for n in range(1, 6)]
    assert set(units[4].depends_on) == {"feature/3", "feature/4"}
    # With no independent group, the tail alone, as before.
    chain = plan(group(1), group(2), group(3), group(4, flag="acceptance", tier="e2e-test"))
    assert chain[3].depends_on == ("feature/3",)


def test_a_narrow_unit_after_both_depends_on_the_acceptance_unit_and_the_independent_unit() -> None:
    units = plan(
        group(1),
        group(2),
        group(3),
        group(4, independent=True, repo="platform"),
        group(5, flag="acceptance", tier="e2e-test"),
        group(6, flag="narrow"),
    )

    assert set(units[5].depends_on) == {"feature/5", "feature/4"}
