"""The local metric records as lines of the usage ledger: their shape, how they
are read, and that archiving a change keeps them (spec: telemetry)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit import config
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.archive import archive_ready_changes
from agent_build_kit.pipeline.metric_records import read_metrics, record_metric
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME, read_ledger
from agent_build_kit.pipeline.usage_report import roll_up_change
from tests.ledger_lines import agent_line, span_line
from tests.pipeline.test_archive import FakeRunner, make_change, unit

CHANGE = "add-marker"


def write(path: Path, lines: list[dict | str]) -> None:
    text = "".join((line if isinstance(line, str) else json.dumps(line)) + "\n" for line in lines)
    path.write_text(text)


def metric(change: str = CHANGE, name: str = "abk.tick.duration", **fields) -> dict:
    return {
        "kind": "metric",
        "at": "2026-01-01T10:00:00+00:00",
        "metric": name,
        "value": 12.5,
        "attributes": {"outcome": "built"},
        "unit": f"{change}/1",
        "change": change,
        **fields,
    }


def test_a_record_is_appended_to_the_active_installations_ledger() -> None:
    told: list[str] = []
    root = config.active_root()
    assert root is not None
    ledger = Installation(config.active(), root).state_dir / LEDGER_NAME

    record_metric(
        "abk.usage.pauses", 1, told.append, unit="add-marker/1", change=CHANGE, kind="usage"
    )

    (record,) = read_metrics(ledger)
    assert (record.metric, record.value, record.attributes) == (
        "abk.usage.pauses",
        1,
        {"kind": "usage"},
    )
    assert (record.unit, record.change) == ("add-marker/1", CHANGE)
    assert record.at
    assert told == []


def test_the_reader_keeps_only_metric_records_and_skips_a_half_written_line(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / LEDGER_NAME
    write(ledger, [agent_line(), metric(), span_line(), '{"kind": "metric", "metric": "abk.ti'])

    assert [r.metric for r in read_metrics(ledger)] == ["abk.tick.duration"]


def test_a_missing_ledger_holds_no_records(tmp_path: Path) -> None:
    assert read_metrics(tmp_path / LEDGER_NAME) == []


def test_rolling_up_a_change_leaves_its_metric_records_and_rolls_up_its_usage(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / LEDGER_NAME
    records = [
        metric(name="abk.tick.duration"),
        metric(name="abk.review.rounds", value=2, attributes={"repo": "app", "outcome": "open"}),
        metric(name="abk.usage.pauses", value=1, attributes={"kind": "usage"}),
        metric(name="abk.checks.failures", value=1, attributes={"check": "types", "round": 1}),
        metric(name="abk.unit.duration", attributes={"outcome": "open"}),
        metric("other", name="abk.tick.duration"),
    ]
    write(ledger, [agent_line(), agent_line(node="review"), span_line(), *records])
    before = read_metrics(ledger)

    roll_up_change(ledger, CHANGE)

    assert read_metrics(ledger) == before
    kinds = [json.loads(line)["kind"] for line in ledger.read_text().splitlines()]
    assert kinds.count("summary") == 1
    assert "agent" not in kinds and "span" not in kinds


def test_archiving_a_change_keeps_its_metric_records(tmp_path: Path) -> None:
    ledger = tmp_path / LEDGER_NAME
    write(ledger, [agent_line(), metric(), metric(name="abk.usage.pauses", value=1)])
    make_change(tmp_path, CHANGE)

    archived = archive_ready_changes(
        [unit(f"{CHANGE}/1")], planning_repo=tmp_path, run=FakeRunner(), usage_ledger=ledger
    )

    assert archived == [CHANGE]
    assert [r.metric for r in read_metrics(ledger)] == ["abk.tick.duration", "abk.usage.pauses"]
    assert read_ledger(ledger) == [], "the usage was rolled up, not kept as calls"


@pytest.mark.parametrize("change", ["add-marker", "other"])
def test_rolling_up_one_change_keeps_the_records_of_both(tmp_path: Path, change: str) -> None:
    ledger = tmp_path / LEDGER_NAME
    write(ledger, [agent_line(), metric(CHANGE), metric("other")])

    roll_up_change(ledger, change)

    assert {r.change for r in read_metrics(ledger)} == {CHANGE, "other"}
