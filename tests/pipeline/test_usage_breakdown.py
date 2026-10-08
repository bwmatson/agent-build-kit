"""An archived change keeps its breakdown by node, role and model.

Rolling a change up replaces its detail with one summary line per unit; the line
carries a `breakdown` whose items sum to its totals, so the report splits
archived work as it split live work. A summary written before breakdowns existed
still loads, under one labelled row."""

from __future__ import annotations

import json
from pathlib import Path

from agent_build_kit.pipeline.usage_report import Report, ReportRow, build_report, roll_up_change
from tests.factories import stored_unit
from tests.ledger_lines import agent_line, span_line, write_ledger

CHANGE = "add-marker"
UNITS = [stored_unit("add-marker/1", repo="app"), stored_unit("add-marker/2", repo="app")]
GROUPINGS = ("unit", "change", "repo", "day", "node", "role", "model")
SPLIT = ("node", "role", "model")
FIGURES = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)
TIMES = ("agent_ms", "checks_ms", "slot_wait_ms", "pause_wait_ms")


def detail_ledger(tmp_path: Path) -> Path:
    """One unit with calls at two nodes, roles, models and sources, a wait at a
    node that made a call, and a wait at a node that made none."""
    return write_ledger(
        tmp_path / "state" / "usage-ledger.jsonl",
        agent_line(),
        agent_line(
            node="review",
            round=1,
            role="review",
            model="model-b",
            session_id="sess-2",
            cost_usd=0.25,
            duration_ms=30000,
        ),
        agent_line(session_id="sess-3", usage_source="estimated", cost_usd=0.5, duration_ms=1000),
        span_line(node="review", waited="slot", duration_ms=5000),
        span_line(node="plan", waited="slot", duration_ms=4000),
        span_line(node="plan", waited="usage_pause", duration_ms=600),
        span_line(command="uv run pytest", duration_ms=3000),
        agent_line(unit="add-marker/2", session_id="sess-4", cost_usd=2.0),
    )


def summaries(path: Path) -> list[dict]:
    lines = [json.loads(x) for x in path.read_text().splitlines() if x]
    return [x for x in lines if x["kind"] == "summary"]


def summary_of(path: Path, unit: str) -> dict:
    (found,) = [s for s in summaries(path) if s["unit"] == unit]
    return found


def total_of(items: list[dict], side: str, name: str) -> float | None:
    present = [i[side][name] for i in items if i[side][name] is not None]
    return sum(present) if present else None


def rows(report: Report) -> dict[str, dict]:
    """Everything a row says, sources and difference included."""
    return {r.key: r.model_dump() for r in (*report.rows, report.total)}


def row_of(report: Report, key: str) -> ReportRow:
    (row,) = [r for r in report.rows if r.key == key]
    return row


def test_a_summary_has_one_breakdown_item_per_node_role_model_and_source(tmp_path: Path) -> None:
    ledger = detail_ledger(tmp_path)

    roll_up_change(ledger, CHANGE)

    items = summary_of(ledger, "add-marker/1")["breakdown"]
    keys = [(i["node"], i["role"], i["model"], i["usage_source"]) for i in items]
    assert keys == sorted(keys), "the items are ordered by their key"
    assert len(set(keys)) == len(keys)
    assert ("implement", "implement", "model-a", "reported") in keys
    assert ("implement", "implement", "model-a", "estimated") in keys
    assert ("review", "review", "model-b", "reported") in keys
    assert {i["runtime"] for i in items if i["node"] == "review"} == {"claude_code"}


def test_the_items_sum_to_the_summarys_top_level_figures(tmp_path: Path) -> None:
    ledger = detail_ledger(tmp_path)

    roll_up_change(ledger, CHANGE)

    for unit in ("add-marker/1", "add-marker/2"):
        line = summary_of(ledger, unit)
        items = line["breakdown"]
        for side in ("measured", "estimated"):
            assert total_of(items, side, "calls") == line[side]["calls"]
            assert total_of(items, side, "cost_usd") == line[side]["cost_usd"]
            for name in FIGURES:
                assert total_of(items, side, name) == line[side][name]
        for name in TIMES:
            present = [i[name] for i in items if i.get(name) is not None]
            assert (sum(present) if present else None) == line[name], name


def test_a_waiting_node_that_made_no_call_keeps_its_wait_under_the_node(tmp_path: Path) -> None:
    ledger = detail_ledger(tmp_path)

    roll_up_change(ledger, CHANGE)

    items = summary_of(ledger, "add-marker/1")["breakdown"]
    (waiting,) = [i for i in items if i["node"] == "plan"]
    assert (waiting["role"], waiting["model"]) == ("(none)", "(none)")
    assert waiting["slot_wait_ms"] == 4000
    assert waiting["pause_wait_ms"] == 600
    assert waiting["measured"]["calls"] == 0


def test_the_report_by_node_role_and_model_splits_archived_work_as_before(tmp_path: Path) -> None:
    ledger = detail_ledger(tmp_path)
    before = {
        by: build_report(ledger, UNITS, group_by=by, include_estimates=True) for by in GROUPINGS
    }

    roll_up_change(ledger, CHANGE)

    for by, report in before.items():
        after = build_report(ledger, UNITS, group_by=by, include_estimates=True)
        assert rows(after) == rows(report), by
    for by in SPLIT:
        keys = {r.key for r in build_report(ledger, UNITS, group_by=by).rows}
        assert not {k for k in keys if "summary" in k.lower()}, by
    by_node = build_report(ledger, UNITS, group_by="node")
    assert row_of(by_node, "plan").slot_wait_ms == 4000
    assert row_of(by_node, "review").slot_wait_ms == 5000


def test_fractional_costs_and_a_gateway_difference_survive_the_roll_up(tmp_path: Path) -> None:
    costs = (0.123456789, 0.000001234, 0.3333333333, 0.1, 0.2, 0.000000071)
    ledger = write_ledger(
        tmp_path / "state" / "usage-ledger.jsonl",
        *(
            agent_line(
                node=("implement", "review")[i % 2],
                role=("implement", "review")[i % 2],
                session_id=f"sess-{i}",
                cost_usd=cost,
            )
            for i, cost in enumerate(costs)
        ),
        agent_line(
            session_id="sess-g",
            usage_source="gateway",
            input_tokens=120,
            output_tokens=60,
            cost_usd=1.2345678901,
            reported={
                "input_tokens": 100,
                "output_tokens": 55,
                "cache_read_input_tokens": None,
                "cache_creation_input_tokens": None,
            },
            reported_cost_usd=1.0000000001,
        ),
    )
    before = {
        by: build_report(ledger, UNITS, group_by=by, include_estimates=True) for by in GROUPINGS
    }

    roll_up_change(ledger, CHANGE)

    line = summary_of(ledger, "add-marker/1")
    items = line["breakdown"]
    for name in ("input_tokens", "output_tokens", "cost_usd"):
        parts = [i["difference"][name] for i in items if i["difference"]]
        assert round(sum(parts), 10) == line["difference"][name], name
    for by, report in before.items():
        after = build_report(ledger, UNITS, group_by=by, include_estimates=True)
        assert rows(after) == rows(report), by


def test_rolling_a_change_up_twice_leaves_the_file_unchanged(tmp_path: Path) -> None:
    ledger = detail_ledger(tmp_path)
    roll_up_change(ledger, CHANGE)
    assert "breakdown" in summary_of(ledger, "add-marker/1")
    once = ledger.read_bytes()

    roll_up_change(ledger, CHANGE)

    assert ledger.read_bytes() == once


def old_summary(**fields) -> dict:
    """A summary line as written before breakdowns: totals only."""
    return {
        "kind": "summary",
        "at": "2026-01-01T10:00:00+00:00",
        "unit": "add-marker/1",
        "change": CHANGE,
        "repo": "app",
        "measured": {
            "calls": 3,
            "input_tokens": 300,
            "output_tokens": 150,
            "cache_read_input_tokens": 3000,
            "cache_creation_input_tokens": 600,
            "cost_usd": 4.5,
        },
        "estimated": {"calls": 0},
        "agent_ms": 120000,
        "checks_ms": 3000,
        "slot_wait_ms": 9000,
        "sources": ["reported"],
        **fields,
    }


def test_an_old_summary_loads_and_totals_under_one_labelled_row(tmp_path: Path) -> None:
    ledger = write_ledger(
        tmp_path / "usage-ledger.jsonl",
        old_summary(),
        agent_line(unit="feature/1", change="feature"),
    )
    units = [*UNITS, stored_unit("feature/1", change="feature", repo="app")]

    by_unit = build_report(ledger, units, group_by="unit")

    assert row_of(by_unit, "add-marker/1").measured.calls == 3
    assert by_unit.total.measured.calls == 4
    labels = set()
    for by in SPLIT:
        report = build_report(ledger, units, group_by=by)
        (archived,) = [r for r in report.rows if r.measured.calls == 3]
        assert archived.measured.cost_usd == 4.5
        assert archived.agent_ms == 120000
        assert "breakdown" in archived.key.lower(), "the label says it has none"
        labels.add(archived.key)
    assert len(labels) == 1, "one label in all three views"


def test_an_old_summary_merged_with_new_detail_keeps_its_totals_under_one_item(
    tmp_path: Path,
) -> None:
    old_only = write_ledger(tmp_path / "old" / "ledger.jsonl", old_summary())
    (label_row,) = build_report(old_only, UNITS, group_by="node").rows
    label = label_row.key
    ledger = write_ledger(
        tmp_path / "state" / "ledger.jsonl", old_summary(), agent_line(session_id="sess-9")
    )

    roll_up_change(ledger, CHANGE)

    line = summary_of(ledger, "add-marker/1")
    assert line["measured"]["calls"] == 4
    assert line["measured"]["cost_usd"] == 5.5
    items = line["breakdown"]
    (carried,) = [i for i in items if i["node"] == label]
    assert carried["measured"]["calls"] == 3
    assert carried["measured"]["cost_usd"] == 4.5
    assert carried["agent_ms"] == 120000
    assert carried["slot_wait_ms"] == 9000
    assert [i["node"] for i in items if i["node"] == "implement"] == ["implement"]
    assert total_of(items, "measured", "calls") == 4
