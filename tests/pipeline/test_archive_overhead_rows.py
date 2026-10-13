"""Archiving a change leaves the calls that belong to no change as they are (spec: usage-reporting,
every agent call is recorded): the rows stay in the ledger line for line, and the report's totals
and its pipeline overhead do not move."""

from __future__ import annotations

import json
from pathlib import Path

from agent_build_kit.pipeline.archive import archive_ready_changes
from agent_build_kit.pipeline.usage_report import build_report
from tests.factories import stored_unit
from tests.ledger_lines import agent_line, write_ledger
from tests.pipeline.test_usage_report import FakeRunner, merged

OVERHEAD = {"unit": "", "change": "", "repo": "", "round": 0, "role": "generic"}


def overhead_rows() -> list[dict]:
    return [
        agent_line(**OVERHEAD, node="track_health", session_id=None, cost_usd=0.125),
        agent_line(**OVERHEAD, node="chat", session_id=None, cost_usd=0.25),
    ]


def test_archiving_leaves_rows_with_no_change_as_they_are(tmp_path: Path) -> None:
    (tmp_path / "openspec" / "changes" / "add-marker").mkdir(parents=True)
    ledger = write_ledger(tmp_path / "state" / "usage-ledger.jsonl", agent_line(), *overhead_rows())
    units = [merged("add-marker/1")]
    reporting = [*units, stored_unit("feature/1", change="feature")]
    before = build_report(ledger, reporting, group_by="unit", include_estimates=True)
    assert [r.key for r in before.overhead] == ["chat", "track_health"]

    archive_ready_changes(units, planning_repo=tmp_path, run=FakeRunner(), usage_ledger=ledger)

    lines = [json.loads(x) for x in ledger.read_text().splitlines() if x]
    kept = [x for x in lines if x["kind"] == "agent"]
    assert [(x["node"], x["cost"]["incremental_usd"]) for x in kept] == [
        ("track_health", 0.125),
        ("chat", 0.25),
    ]
    after = build_report(ledger, reporting, group_by="unit", include_estimates=True)
    assert after.total == before.total
    assert after.overhead == before.overhead
