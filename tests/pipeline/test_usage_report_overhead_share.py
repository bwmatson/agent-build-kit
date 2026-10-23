"""The `pipeline overhead` section states what its rows cost and the share of the ledger's cost that
is, because the usage estimate counts that cost (spec: usage-reporting, calls with no unit are
shown as pipeline overhead)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.usage_report import GROUPINGS, build_report, render_table
from tests.factories import stored_unit
from tests.ledger_lines import agent_line, write_ledger

UNITS = [stored_unit("add-marker/1", repo="app")]
OVERHEAD = {
    "unit": "",
    "round": 0,
    "role": "generic",
    "session_id": None,
    "usage_source": "reported",
}


def costed_ledger(tmp_path: Path) -> Path:
    """Overhead rows costing $21.86 in a ledger costing $354.00."""
    return write_ledger(
        tmp_path / "ledger.jsonl",
        agent_line(cost_usd=332.14),
        agent_line(**OVERHEAD, node="plan", change="add-marker", repo="", cost_usd=20.0),
        agent_line(**OVERHEAD, node="track_health", change="", repo="app", cost_usd=1.86),
    )


def heading(table: str) -> str:
    return next(line for line in table.splitlines() if "pipeline overhead" in line)


def test_the_section_states_the_overhead_cost_and_its_share_of_the_ledger(tmp_path: Path) -> None:
    report = build_report(costed_ledger(tmp_path), UNITS, group_by="unit")

    line = heading(render_table(report))

    assert "$21.86" in line
    assert "6%" in line
    assert report.overhead_cost_usd == pytest.approx(21.86)
    assert report.overhead_share == pytest.approx(21.86 / 354.0)


def test_a_ledger_with_no_cost_states_the_section_without_dividing_by_zero(tmp_path: Path) -> None:
    path = write_ledger(
        tmp_path / "ledger.jsonl",
        agent_line(cost_usd=None),
        agent_line(**OVERHEAD, node="plan", change="add-marker", repo="", cost_usd=None),
    )

    report = build_report(path, UNITS, group_by="unit")

    assert [r.key for r in report.overhead] == ["plan"]
    assert report.overhead_share is None
    assert "$" in heading(render_table(report))


def test_the_lines_per_node_and_the_totals_are_as_they_were(tmp_path: Path) -> None:
    path = costed_ledger(tmp_path)

    report = build_report(path, UNITS, group_by="unit")

    assert [r.key for r in report.overhead] == ["plan", "track_health"]
    assert [r.measured.cost_usd for r in report.overhead] == [20.0, 1.86]
    for by in GROUPINGS:
        other = build_report(path, UNITS, group_by=by)
        assert other.total.measured.cost_usd == pytest.approx(354.0), by
