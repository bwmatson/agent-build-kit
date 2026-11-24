"""A ledger written partly before the test-kind rename reads every line with the new value, so
the metrics view groups a kind under one label."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.compat_names import old_spelling
from agent_build_kit.model import TestTier
from agent_build_kit.serve.metrics import Instrument, LocalSource
from tests.ledger_lines import agent_line, write_ledger

KINDS = [(old_spelling(kind), kind.value) for kind in (TestTier.UNIT_TEST, TestTier.E2E_TEST)]
INTEGRATION = TestTier.INTEGRATION_TEST.value
DAY = "2026-01-01T10:00:00+00:00"


def metric_line(tier: str) -> dict:
    return {
        "kind": "metric",
        "at": DAY,
        "metric": "abk.unit.duration",
        "value": 60.0,
        "attributes": {"repo": "app", "tier": tier, "outcome": "open"},
    }


@pytest.mark.parametrize("old, new", KINDS)
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


@pytest.mark.parametrize("old, new", KINDS)
def test_metric_lines_of_either_spelling_are_one_label(tmp_path: Path, old: str, new: str) -> None:
    ledger = write_ledger(tmp_path / "usage-ledger.jsonl", metric_line(old), metric_line(new))
    duration = Instrument(
        name="abk.unit.duration", type="histogram", attributes=("repo", "tier", "outcome")
    )

    series = LocalSource(ledger).series(duration)

    assert [s.labels["tier"] for s in series] == [new]


def test_an_integration_test_line_is_its_own_label_beside_the_old_spelling_of_unit_test(
    tmp_path: Path,
) -> None:
    ledger = write_ledger(
        tmp_path / "usage-ledger.jsonl",
        agent_line(cost_usd=1.0, tier=INTEGRATION),
        agent_line(cost_usd=2.0, tier=old_spelling(TestTier.UNIT_TEST), unit="add-marker/2"),
        agent_line(cost_usd=4.0, tier=TestTier.UNIT_TEST.value, unit="add-marker/3"),
    )
    cost = Instrument(name="abk.agent.cost", type="counter", attributes=("tier",))

    series = LocalSource(ledger).series(cost)

    totals = {s.labels["tier"]: sum(p[1] for p in s.points) for s in series}
    assert totals == {INTEGRATION: pytest.approx(1.0), "unit-test": pytest.approx(6.0)}


def test_an_integration_test_metric_line_keeps_its_value(tmp_path: Path) -> None:
    ledger = write_ledger(tmp_path / "usage-ledger.jsonl", metric_line(INTEGRATION))
    duration = Instrument(
        name="abk.unit.duration", type="histogram", attributes=("repo", "tier", "outcome")
    )

    series = LocalSource(ledger).series(duration)

    assert [s.labels["tier"] for s in series] == [INTEGRATION]
