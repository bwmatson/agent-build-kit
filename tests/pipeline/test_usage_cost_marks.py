"""Rows a retired repair wrote are still read: the basis `backfilled` on a call, and
`cumulative_summed` on a summary, which the roll-up keeps when it folds later rows in."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.pipeline.usage_ledger import CostBasis, read_ledger
from agent_build_kit.pipeline.usage_report import build_report, roll_up_change
from tests.ledger_lines import costed_line, write_ledger


def lines_of(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x]


def test_a_call_with_basis_backfilled_loads_and_its_increment_is_summed(tmp_path: Path) -> None:
    ledger = write_ledger(
        tmp_path / "ledger.jsonl",
        costed_line(2.0, 2.0, basis="backfilled", session_id="old", node="tests"),
        costed_line(1.5, 3.5, basis="backfilled", session_id="old", node="implement", resumed=True),
    )

    records = read_ledger(ledger)
    report = build_report(ledger, [], group_by="unit")

    assert {r.cost.basis for r in records if r.cost} == {CostBasis.BACKFILLED}
    assert report.total.measured.cost_usd == pytest.approx(3.5)


def test_a_summary_marked_cumulative_summed_loads_and_keeps_its_mark_when_rolled_up_again(
    tmp_path: Path,
) -> None:
    ledger = write_ledger(
        tmp_path / "ledger.jsonl",
        costed_line(2.0, 2.0, basis="first", session_id="s", node="tests"),
    )
    roll_up_change(ledger, "add-marker")
    marked = [line | {"cost_basis": "cumulative_summed"} for line in lines_of(ledger)]
    later = costed_line(
        1.0, 3.0, session_id="s", node="implement", resumed=True, at="2026-01-01T11:00:00+00:00"
    )
    write_ledger(ledger, *marked, later)

    build_report(ledger, [], group_by="unit")
    roll_up_change(ledger, "add-marker")

    summaries = [x for x in lines_of(ledger) if x["kind"] == "summary"]
    assert [s["cost_basis"] for s in summaries] == ["cumulative_summed"]
