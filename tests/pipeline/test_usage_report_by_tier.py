"""`build_report(group_by="tier")` groups the ledger's agent rows by the review tier planned for
each unit and shows the forecast recorded at admission against what was spent (spec:
usage-reporting)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.usage_report import Report, TierRow, build_report
from agent_build_kit.pipeline.verdict import ReviewTier
from tests.factories import stored_unit
from tests.ledger_lines import agent_line, write_ledger
from tests.usage_forecast_fixtures import forecast_row, write_forecast_rows, write_verdict_file

AUTO = ReviewTier.AUTO
FULL = ReviewTier.FULL


class Files:
    def __init__(self, root: Path) -> None:
        self.ledger = root / "usage-ledger.jsonl"
        self.verdicts = root / "verdicts.json"
        self.forecasts = root / "usage-forecasts.jsonl"


@pytest.fixture
def files(tmp_path: Path) -> Files:
    return Files(tmp_path)


def spend(unit: str, usd: float, *, node: str = "implement", kind: str = "unit-test") -> dict:
    return agent_line(
        unit=unit,
        change=unit.split("/")[0],
        node=node,
        role=node,
        tier=kind,
        cost_usd=usd,
        session_id=f"{unit}-{node}",
    )


def report(files: Files, *lines: dict, units: list[StoredUnit] | None = None) -> Report:
    write_ledger(files.ledger, *lines)
    return build_report(
        files.ledger,
        units or [],
        group_by="tier",
        verdicts=files.verdicts,
        forecasts=files.forecasts,
    )


def tier(found: Report, name: str) -> TierRow:
    [row] = [t for t in found.tiers if t.tier == name]
    return row


def test_forecast_against_actual_per_tier(files: Files) -> None:
    spent = {"a/1": 2.00, "b/1": 2.60, "c/1": 3.40}
    write_verdict_file(files.verdicts, dict.fromkeys(spent, AUTO))
    write_forecast_rows(files.forecasts, [forecast_row(u, AUTO, 2.55) for u in spent])

    row = tier(report(files, *(spend(u, usd) for u, usd in spent.items())), "auto")

    assert row.units == 3
    assert row.forecast_usd == pytest.approx(7.65)
    assert row.spent_usd == pytest.approx(8.00)
    assert row.ratio == pytest.approx(8.00 / 7.65)
    assert round(row.ratio or 0, 2) == 1.05
    # $2.60 and $3.40 both exceed $2.55; the spec's "one over" miscounts its own figures.
    assert row.over == 2
    assert row.unforecast == 0


def test_each_tier_has_its_own_row(files: Files) -> None:
    write_verdict_file(files.verdicts, {"a/1": AUTO, "f/1": FULL, "g/1": FULL})
    write_forecast_rows(
        files.forecasts,
        [
            forecast_row("a/1", AUTO, 2.55),
            forecast_row("f/1", FULL, 3.42),
            forecast_row("g/1", FULL, 3.42),
        ],
    )

    found = report(files, spend("a/1", 2.0), spend("f/1", 3.0), spend("g/1", 4.0))

    full = tier(found, "full")
    assert (full.units, full.over) == (2, 1)
    assert full.forecast_usd == pytest.approx(6.84)
    assert full.spent_usd == pytest.approx(7.00)
    assert round(full.ratio or 0, 2) == 1.02
    assert tier(found, "auto").units == 1


def test_a_unit_with_no_forecast_row_is_unforecast_and_left_out_of_the_ratio(files: Files) -> None:
    write_verdict_file(files.verdicts, {"a/1": AUTO, "old/1": AUTO})
    write_forecast_rows(files.forecasts, [forecast_row("a/1", AUTO, 2.0)])

    row = tier(report(files, spend("a/1", 3.0), spend("old/1", 10.0)), "auto")

    assert row.units == 2
    assert row.unforecast == 1
    assert row.forecast_usd == pytest.approx(2.0)
    assert row.ratio == pytest.approx(1.5)
    assert row.spent_usd == pytest.approx(13.0)


def test_a_unit_with_no_tier_is_under_none(files: Files) -> None:
    write_verdict_file(files.verdicts, {})

    found = report(files, spend("a/1", 1.0))

    assert [t.tier for t in found.tiers] == ["(none)"]
    assert [r.key for r in found.rows] == ["(none)"]


def test_the_stored_review_tier_stands_in_when_there_is_no_verdict_record(files: Files) -> None:
    write_verdict_file(files.verdicts, {})

    found = report(files, spend("a/1", 1.0), units=[stored_unit("a/1", review_tier="light")])

    assert [t.tier for t in found.tiers] == ["light"]


def test_the_planned_estimate_wins_over_the_stored_review_tier(files: Files) -> None:
    write_verdict_file(files.verdicts, {"a/1": FULL})

    found = report(files, spend("a/1", 1.0), units=[stored_unit("a/1", review_tier="auto")])

    assert [t.tier for t in found.tiers] == ["full"]


def test_test_kinds_make_no_group(files: Files) -> None:
    write_verdict_file(files.verdicts, {"a/1": AUTO, "b/1": FULL})

    found = report(files, spend("a/1", 1.0, kind="unit-test"), spend("b/1", 1.0, kind="e2e-test"))

    names = {t.tier for t in found.tiers} | {r.key for r in found.rows}
    assert names == {"auto", "full"}


def test_a_forecast_recorded_under_other_settings_is_summed_as_recorded(files: Files) -> None:
    write_verdict_file(files.verdicts, {"a/1": AUTO, "b/1": AUTO})
    write_forecast_rows(
        files.forecasts, [forecast_row("a/1", AUTO, 1.0), forecast_row("b/1", AUTO, 9.0)]
    )

    row = tier(report(files, spend("a/1", 1.0), spend("b/1", 1.0)), "auto")

    assert row.forecast_usd == pytest.approx(10.0)


def test_spend_is_split_by_role_and_node(files: Files) -> None:
    write_verdict_file(files.verdicts, {"f/1": FULL})

    row = tier(
        report(
            files,
            spend("f/1", 1.0, node="implement"),
            spend("f/1", 0.5, node="review"),
            spend("f/1", 0.25, node="rework"),
        ),
        "full",
    )

    assert {(s.role, s.node): s.usd for s in row.spend} == {
        ("implement", "implement"): 1.0,
        ("review", "review"): 0.5,
        ("rework", "rework"): 0.25,
    }
