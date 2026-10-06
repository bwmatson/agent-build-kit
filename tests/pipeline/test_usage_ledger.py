"""The ledger's reader: one record per unit, node, round and session, the last
one written; lines from before a field existed still load (spec:
agent-usage-capture, a resumed or re-run call is counted once).
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_build_kit.pipeline.usage_ledger import read_ledger


def line(**fields) -> dict:
    return {
        "kind": "agent",
        "at": "2026-01-01T10:00:00+00:00",
        "unit": "add-marker/1",
        "node": "implement",
        "round": 0,
        "role": "implement",
        "model": "m",
        "runtime": "claude_code",
        "session_id": "sess-1",
        "input_tokens": 10,
        "output_tokens": 20,
        "cost_usd": 0.5,
        "usage_source": "reported",
        **fields,
    }


def write(path: Path, *lines: dict | str) -> Path:
    path.write_text("".join((x if isinstance(x, str) else json.dumps(x)) + "\n" for x in lines))
    return path


def test_the_same_node_and_round_written_twice_is_counted_once_with_the_latest_figures(
    tmp_path: Path,
) -> None:
    ledger = write(
        tmp_path / "usage-ledger.jsonl",
        line(cost_usd=0.5, at="2026-01-01T10:00:00+00:00"),
        line(node="review", round=1, role="review", session_id="sess-2"),
        line(cost_usd=0.9, at="2026-01-01T10:30:00+00:00"),
    )

    records = read_ledger(ledger)

    assert len(records) == 2
    (build,) = [r for r in records if r.node == "implement"]
    assert build.cost_usd == 0.9
    assert sum(r.cost_usd or 0 for r in records) == 0.9 + 0.5


def test_a_round_of_the_same_node_is_its_own_record(tmp_path: Path) -> None:
    ledger = write(
        tmp_path / "usage-ledger.jsonl",
        line(node="review", round=1, role="review"),
        line(node="review", round=2, role="review"),
    )

    assert [r.round for r in read_ledger(ledger)] == [1, 2]


def test_a_new_session_for_the_same_node_and_round_is_spend_of_its_own(tmp_path: Path) -> None:
    ledger = write(
        tmp_path / "usage-ledger.jsonl",
        line(session_id="sess-1"),
        line(session_id="sess-2"),
        line(session_id="sess-2", cost_usd=0.7),
    )

    records = read_ledger(ledger)

    assert {r.session_id: r.cost_usd for r in records} == {"sess-1": 0.5, "sess-2": 0.7}


def test_a_line_from_before_a_field_existed_loads_with_that_field_absent(tmp_path: Path) -> None:
    old = {
        "at": "2025-06-01T09:00:00+00:00",
        "unit": "add-marker/1",
        "node": "implement",
        "round": 0,
        "role": "implement",
        "model": "m",
        "runtime": "claude_code",
        "cost_usd": 0.25,
        "usage_source": "reported",
    }
    ledger = write(tmp_path / "usage-ledger.jsonl", old)

    (record,) = read_ledger(ledger)

    assert record.cost_usd == 0.25
    assert record.input_tokens is None
    assert record.cache_read_input_tokens is None
    assert record.duration_ms is None


def test_a_line_with_a_field_a_later_version_adds_still_loads(tmp_path: Path) -> None:
    ledger = write(tmp_path / "usage-ledger.jsonl", line(a_later_field={"x": [1]}))

    (record,) = read_ledger(ledger)

    assert record.cost_usd == 0.5


def test_a_missing_ledger_reads_as_empty(tmp_path: Path) -> None:
    assert read_ledger(tmp_path / "none-yet.jsonl") == []


def test_a_half_written_line_costs_only_itself(tmp_path: Path) -> None:
    ledger = write(
        tmp_path / "usage-ledger.jsonl",
        line(),
        '{"kind": "agent", "at": "2026-01-01T10:',
        line(node="review", round=1, role="review"),
    )

    assert [r.node for r in read_ledger(ledger)] == ["implement", "review"]
