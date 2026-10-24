"""`abk report --by tier` prints the review-tier table and `--json` the same figures; the other
groupings are as they were (spec: usage-reporting)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.usage_report import GROUPINGS
from agent_build_kit.pipeline.verdict import ReviewTier
from tests.conftest import make_installation
from tests.ledger_lines import agent_line, write_ledger
from tests.usage_forecast_fixtures import forecast_row, write_forecast_rows, write_verdict_file


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    installation = make_installation(tmp_path / "planning")
    (installation.root / "abk.yaml").write_text(dump(installation.config))
    monkeypatch.chdir(installation.root)
    state = installation.state_dir
    write_verdict_file(state / "verdicts.json", {"a/1": ReviewTier.AUTO, "b/1": ReviewTier.FULL})
    write_forecast_rows(
        state / "usage-forecasts.jsonl",
        [forecast_row("a/1", ReviewTier.AUTO, 2.55), forecast_row("b/1", ReviewTier.FULL, 3.42)],
    )
    write_ledger(
        state / "usage-ledger.jsonl",
        agent_line(unit="a/1", change="a", cost_usd=2.0, session_id="s1", tier="unit-test"),
        agent_line(unit="b/1", change="b", cost_usd=4.0, session_id="s2", tier="e2e-test"),
    )
    return installation


def test_the_choices_include_tier() -> None:
    assert "tier" in GROUPINGS


def test_by_tier_json_carries_the_figures(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["report", "--by", "tier", "--json"]) == 0

    tiers = {t["tier"]: t for t in json.loads(capsys.readouterr().out)["tiers"]}
    assert set(tiers) == {"auto", "full"}
    assert tiers["auto"]["forecast_usd"] == pytest.approx(2.55)
    assert tiers["full"]["spent_usd"] == pytest.approx(4.0)
    assert tiers["full"]["over"] == 1
    assert tiers["auto"]["unforecast"] == 0


def test_by_tier_table_has_a_row_for_each_tier_and_none_for_a_test_kind(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["report", "--by", "tier"]) == 0

    heads = [line.split()[0] for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert {"auto", "full"} <= set(heads)
    assert "unit-test" not in heads
    assert "e2e-test" not in heads
