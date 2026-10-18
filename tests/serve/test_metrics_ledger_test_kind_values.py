"""A ledger written partly before the test-kind rename reads every line with the new value, so
the metrics view groups a kind under one label."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.serve.metrics import Instrument, LocalSource
from tests.ledger_lines import agent_line, write_ledger

DAY = "2026-01-01T10:00:00+00:00"


def metric_line(tier: str) -> dict:
    return {
        "kind": "metric",
        "at": DAY,
        "metric": "abk.unit.duration",
        "value": 60.0,
        "attributes": {"repo": "app", "tier": tier, "outcome": "open"},
    }


@pytest.mark.parametrize("old, new", [("unit-test", "unit-test"), ("e2e-test", "e2e-test")])
def test_agent_lines_of_either_spelling_are_one_label(tmp_path: Path, old: str, new: str) -> None:
    ledger = write_ledger(
        tmp_path / "usage-ledger.jsonl",
        agent_line(cost_usd=1.0, tier=old),
        agent_line(cost_usd=2.0, tier=new, unit="add-marker/2"),
        agent_line(cost_usd=4.0, tier="", unit="add-marker/3"),
    )
    cost = Instrument(name="abk.agent.cost", type="counter", attributes=("tier",))

    series = LocalSource(ledger).series(cost)

    totals = {s.labels["tier"]: sum(p[1] for p in s.points) for s in series}
    assert totals == {new: pytest.approx(3.0), "": pytest.approx(4.0)}


@pytest.mark.parametrize("old, new", [("unit-test", "unit-test"), ("e2e-test", "e2e-test")])
def test_metric_lines_of_either_spelling_are_one_label(tmp_path: Path, old: str, new: str) -> None:
    ledger = write_ledger(tmp_path / "usage-ledger.jsonl", metric_line(old), metric_line(new))
    duration = Instrument(
        name="abk.unit.duration", type="histogram", attributes=("repo", "tier", "outcome")
    )

    series = LocalSource(ledger).series(duration)

    assert [s.labels["tier"] for s in series] == [new]
