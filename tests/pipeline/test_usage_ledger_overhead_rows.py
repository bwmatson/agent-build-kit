"""A call made outside the unit graph is its own record, however many share a unit, a node or a
session (spec: usage-accounting, a row of a node outside the unit graph's call nodes).

The unit graph's own rules (a re-run replaces, a resumed call adds, an older ledger loads
unchanged) are pinned in `test_usage_ledger.py`.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.usage_ledger import read_ledger
from tests.pipeline.test_usage_ledger import line, spend, write


def at(minute: int) -> str:
    return f"2026-01-01T10:{minute:02d}:00+00:00"


def test_two_restack_rows_of_one_unit_in_one_session_are_two_records_whose_spend_sums(
    tmp_path: Path,
) -> None:
    ledger = write(
        tmp_path / "usage-ledger.jsonl",
        line(node="restack", role="generic", session_id="sess-r", cost_usd=0.3, at=at(1)),
        line(node="restack", role="generic", session_id="sess-r", cost_usd=0.2, at=at(2)),
    )

    records = read_ledger(ledger)

    assert len(records) == 2
    assert round(sum(spend(r) or 0 for r in records), 6) == 0.5


def test_two_restack_rows_of_one_unit_in_a_session_the_other_started_are_two_records(
    tmp_path: Path,
) -> None:
    ledger = write(
        tmp_path / "usage-ledger.jsonl",
        line(node="restack", session_id="sess-a", cost_usd=0.3, at=at(1)),
        line(node="restack", session_id="sess-b", resumed=True, cost_usd=0.4, at=at(2)),
    )

    records = read_ledger(ledger)

    assert len(records) == 2
    assert round(sum(spend(r) or 0 for r in records), 6) == 0.7


def test_plan_and_chat_rows_with_no_unit_are_each_a_record(tmp_path: Path) -> None:
    ledger = write(
        tmp_path / "usage-ledger.jsonl",
        line(unit="", node="plan", session_id=None, cost_usd=0.1, at=at(1)),
        line(unit="", node="plan", session_id=None, cost_usd=0.1, at=at(2)),
        line(unit="", node="chat", session_id="sess-c", cost_usd=0.1, at=at(3)),
        line(unit="", node="chat", session_id="sess-c", cost_usd=0.1, at=at(4)),
        line(unit="", node="chat", session_id="sess-c", cost_usd=0.1, at=at(5)),
    )

    records = read_ledger(ledger)

    assert len(records) == 5
    assert round(sum(spend(r) or 0 for r in records), 6) == 0.5
