"""The history of a review tier is the units whose verdict record is final and planned that
tier, joined to the ledger by unit id; the ledger's own `tier` is the test kind
(spec: usage-pause)."""

from agent_build_kit.pipeline.usage_forecast_history import gather_history
from agent_build_kit.pipeline.verdict import ReviewTier
from tests.usage_forecast_fixtures import Fixture, call

AUTO = ReviewTier.AUTO
FULL = ReviewTier.FULL


def test_the_history_is_by_planned_tier_whatever_test_kind_the_rows_carry() -> None:
    fixture = Fixture()
    a = fixture.unit("a", AUTO, [("review", 1, 1.0)], kind="unit-test")
    b = fixture.unit("b", AUTO, [("review", 1, 1.0)], kind="e2e-test")
    fixture.unit("c", FULL, [("review", 1, 1.0)], kind="unit-test")

    history = gather_history(fixture.records, fixture.verdicts, AUTO)

    assert history.tier == AUTO
    assert sorted(u.unit for u in history.units) == [a, b]


def test_a_unit_with_no_final_verdict_is_in_no_tier() -> None:
    fixture = Fixture()
    fixture.unit("running", AUTO, [("review", 1, 1.0)], final=False)
    fixture.records.append(call("ghost/1", "review", 1, 1.0))

    for tier in ReviewTier:
        assert gather_history(fixture.records, fixture.verdicts, tier).units == ()


def test_overhead_rows_are_not_unit_cells() -> None:
    fixture = Fixture()
    unit = fixture.unit("a", AUTO, [("review", 1, 1.0)])
    for node in ("plan", "restack", "track_health"):
        fixture.records.append(call("", node, 0, 0.5))
        fixture.records.append(call(unit, node, 0, 0.5))

    [found] = gather_history(fixture.records, fixture.verdicts, AUTO).units

    assert [c.node for c in found.calls] == ["review"]


def test_a_unit_is_counted_once_however_many_rows_it_has_in_a_cell() -> None:
    fixture = Fixture()
    fixture.unit("a", AUTO, [("review", 1, 1.0), ("review", 1, 0.5), ("review", 1, 0.25)])

    history = gather_history(fixture.records, fixture.verdicts, AUTO)

    assert len(history.units) == 1
    assert len(history.units[0].calls) == 3


def test_a_unit_carries_its_recorded_changed_lines() -> None:
    fixture = Fixture()
    fixture.unit("a", AUTO, [("review", 1, 1.0)], lines=42)

    [found] = gather_history(fixture.records, fixture.verdicts, AUTO).units

    assert found.lines == 42
