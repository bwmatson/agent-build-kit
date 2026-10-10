"""The ledger's reader adds only incremental figures, reads a line with the `cost` object from
the object alone, and reads one without it as legacy (spec: agent-usage-capture, The ledger's
reader adds only incremental figures; A record without a cost object is read as legacy)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.usage_ledger import CostBasis, read_ledger
from tests.ledger_lines import agent_line, costed_line, legacy_line, worked_session, write_ledger


def test_a_session_of_several_calls_sums_its_increments_to_its_final_cumulative(
    tmp_path: Path,
) -> None:
    ledger = write_ledger(tmp_path / "ledger.jsonl", *worked_session())

    records = read_ledger(ledger)

    costs = [r.cost for r in records]
    assert all(c is not None for c in costs)
    assert sum(c.incremental_usd or 0 for c in costs if c) == pytest.approx(25.39)
    finals = [c.cumulative_usd for c in costs if c and c.cumulative_usd is not None]
    assert max(finals) == pytest.approx(25.39)


def test_one_record_per_unit_node_and_round_is_kept_and_a_resumed_call_adds_to_it(
    tmp_path: Path,
) -> None:
    ledger = write_ledger(tmp_path / "ledger.jsonl", *worked_session())

    records = read_ledger(ledger)

    # nine calls: the rework calls of rounds 0 and 1 resumed into the call they continued
    assert [(r.node, r.round) for r in records] == [
        ("tests", 0),
        ("implement", 0),
        ("rework", 1),
        ("rework", 2),
        ("rework", 0),
        ("fix_checks", 1),
    ]
    increments = {(r.node, r.round): r.cost.incremental_usd for r in records if r.cost}
    assert increments[("rework", 1)] == pytest.approx(7.69 + 0.78 + 1.47)
    assert increments[("rework", 0)] == pytest.approx(4.38 + 2.52)


def test_a_combined_record_carries_the_last_parts_cumulative_figure(tmp_path: Path) -> None:
    ledger = write_ledger(tmp_path / "ledger.jsonl", *worked_session())

    records = {(r.node, r.round): r.cost for r in read_ledger(ledger)}

    rework = records[("rework", 1)]
    assert rework is not None
    assert rework.cumulative_usd == pytest.approx(25.39)
    assert rework.incremental_usd == pytest.approx(7.69 + 0.78 + 1.47)


def test_a_call_with_no_incremental_figure_adds_nothing_to_a_combined_record(
    tmp_path: Path,
) -> None:
    ledger = write_ledger(
        tmp_path / "ledger.jsonl",
        costed_line(2.0, 2.0, basis="first", session_id="s", at="2026-01-01T10:00:00+00:00"),
        costed_line(
            None, 5.0, basis="unknown", session_id="s", resumed=True, at="2026-01-01T10:01:00+00:00"
        ),
    )

    (record,) = read_ledger(ledger)

    assert record.cost is not None
    assert record.cost.incremental_usd == pytest.approx(2.0)
    assert record.cost.cumulative_usd == pytest.approx(5.0)


def test_a_line_with_the_object_ignores_flat_fields(tmp_path: Path) -> None:
    line = costed_line(2.86, 5.49) | {"cost_usd": 99.0, "reported_cost_usd": 77.0}
    ledger = write_ledger(tmp_path / "ledger.jsonl", line)

    (record,) = read_ledger(ledger)

    assert record.cost is not None
    assert record.cost.incremental_usd == pytest.approx(2.86)
    assert record.cost.basis == CostBasis.DERIVED
    assert record.cost.legacy_usd is None
    assert "cost_usd" not in record.model_dump(), "no flat figure beside the object"


def test_a_line_with_a_flat_figure_and_no_object_is_read_as_legacy(tmp_path: Path) -> None:
    ledger = write_ledger(tmp_path / "ledger.jsonl", legacy_line(13.18))

    (record,) = read_ledger(ledger)

    assert record.cost is not None
    assert record.cost.basis == CostBasis.LEGACY
    assert record.cost.incremental_usd is None
    assert record.cost.cumulative_usd is None
    assert record.cost.legacy_usd == pytest.approx(13.18)


def test_a_legacy_figure_is_never_added_to_an_incremental_one(tmp_path: Path) -> None:
    ledger = write_ledger(
        tmp_path / "ledger.jsonl",
        legacy_line(13.18, node="tests", session_id="old"),
        costed_line(2.0, 2.0, basis="first", node="implement", session_id="new"),
    )

    records = read_ledger(ledger)

    incremental = sum(r.cost.incremental_usd or 0 for r in records if r.cost)
    assert incremental == pytest.approx(2.0)
    assert sorted(r.cost.legacy_usd for r in records if r.cost and r.cost.legacy_usd) == [13.18]


def test_a_legacy_line_read_back_with_unknown_fields_still_loads(tmp_path: Path) -> None:
    ledger = write_ledger(
        tmp_path / "ledger.jsonl",
        legacy_line(1.5) | {"field_from_a_later_version": {"nested": [1, 2]}},
    )

    (record,) = read_ledger(ledger)

    assert record.cost is not None
    assert record.cost.legacy_usd == pytest.approx(1.5)


def test_a_line_whose_cost_is_the_wrong_type_reads_as_absent(tmp_path: Path) -> None:
    line = agent_line() | {"cost": {"incremental_usd": "a lot", "basis": "derived"}}
    ledger = write_ledger(tmp_path / "ledger.jsonl", line)

    records = read_ledger(ledger)

    assert [r.cost.incremental_usd if r.cost else None for r in records] == [None]
