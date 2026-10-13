"""The report shows the calls made outside any unit as `pipeline overhead` (spec: usage-reporting,
every agent call is recorded).

A call with no unit is a row of its node in the by-unit view, under one section; a `restack`
call has a unit and stays on it. Every grouping still sums to the ledger's total, and the waits
report, built from spans and the unit graph's own agent time, does not move.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.usage_report import (
    GROUPINGS,
    Report,
    ReportRow,
    build_report,
    build_wait_report,
    render_table,
    render_waits,
)
from tests.factories import stored_unit
from tests.ledger_lines import agent_line, span_line, write_ledger

UNITS = [stored_unit("add-marker/1", repo="app")]

OVERHEAD = {
    "unit": "",
    "round": 0,
    "role": "generic",
    "session_id": None,
    "usage_source": "reported",
}
RESTACK = agent_line(node="restack", role="generic", session_id="sess-r", cost_usd=0.5)
PLAN = agent_line(**OVERHEAD, node="plan", change="add-marker", repo="", cost_usd=0.25)
HEALTH = agent_line(**OVERHEAD, node="track_health", change="", repo="app", cost_usd=0.125)
TOTAL_COST = 1.875


def ledger(tmp_path: Path) -> Path:
    return write_ledger(tmp_path / "ledger.jsonl", agent_line(), RESTACK, PLAN, HEALTH)


def section(table: str) -> list[str]:
    """The lines under the `pipeline overhead` heading, up to the next blank line."""
    lines = table.splitlines()
    start = next(i for i, line in enumerate(lines) if "pipeline overhead" in line)
    found: list[str] = []
    for line in lines[start + 1 :]:
        if not line.strip():
            break
        found.append(line)
    return found


def row_of(rows: tuple[ReportRow, ...], key: str) -> ReportRow:
    (row,) = [r for r in rows if r.key == key]
    return row


def cost_of(report: Report) -> float:
    return sum(r.measured.cost_usd or 0 for r in (*report.rows, *report.overhead))


def test_the_by_unit_report_shows_a_pipeline_overhead_line_per_node(tmp_path: Path) -> None:
    report = build_report(ledger(tmp_path), UNITS, group_by="unit")

    lines = section(render_table(report))

    assert [line.split()[0] for line in lines] == ["plan", "track_health"]
    assert [r.key for r in report.overhead] == ["plan", "track_health"]
    assert [r.key for r in report.rows] == ["add-marker/1"]


def test_every_grouping_sums_to_the_same_total(tmp_path: Path) -> None:
    path = ledger(tmp_path)
    assert build_report(path, UNITS, group_by="unit").overhead

    for by in GROUPINGS:
        report = build_report(path, UNITS, group_by=by)
        assert cost_of(report) == pytest.approx(TOTAL_COST), by
        assert report.total.measured.cost_usd == pytest.approx(TOTAL_COST), by


def test_a_restack_row_is_on_its_unit_and_on_its_node_and_not_in_the_overhead(
    tmp_path: Path,
) -> None:
    path = ledger(tmp_path)
    by_unit = build_report(path, UNITS, group_by="unit")

    assert row_of(by_unit.rows, "add-marker/1").measured.calls == 2
    assert "restack" not in {r.key for r in by_unit.overhead}
    assert not any("restack" in line for line in section(render_table(by_unit)))
    by_node = build_report(path, UNITS, group_by="node")
    assert row_of(by_node.rows, "restack").measured.calls == 1
    assert row_of(by_node.rows, "plan").measured.calls == 1


def test_the_overhead_leaves_the_waits_report_as_it_was(tmp_path: Path) -> None:
    spans = [span_line(unit="add-marker/1", change="add-marker", waited="slot", duration_ms=5000)]
    bare = write_ledger(tmp_path / "bare.jsonl", agent_line(), *spans)
    with_overhead = write_ledger(
        tmp_path / "with.jsonl", agent_line(), RESTACK, PLAN, HEALTH, *spans
    )
    decisions = tmp_path / "decisions.jsonl"

    before = build_wait_report(bare, decisions, UNITS)
    after = build_wait_report(with_overhead, decisions, UNITS)

    assert render_waits(after) == render_waits(before)
    assert section(render_table(build_report(with_overhead, UNITS, group_by="unit")))
