"""The usage endpoint carries the overhead's cost and its share of the ledger's cost, the same as
`abk report --json` prints (spec: usage-reporting, the share of the cost)."""

from __future__ import annotations

import json

import httpx
import pytest

from agent_build_kit.cli import main
from agent_build_kit.installation import Installation
from tests.ledger_lines import agent_line, write_ledger
from tests.serving import seed_pipeline

OVERHEAD = {"unit": "", "round": 0, "role": "generic", "session_id": None, "repo": ""}


@pytest.fixture
def ledger(inst: Installation) -> None:
    seed_pipeline(inst)
    write_ledger(
        inst.state_dir / "usage-ledger.jsonl",
        agent_line(unit="feature/1", change="feature", cost_usd=332.14),
        agent_line(**OVERHEAD, node="plan", change="feature", cost_usd=20.0),
        agent_line(**OVERHEAD, node="chat", change="", cost_usd=1.86),
    )


@pytest.mark.usefixtures("ledger")
def test_the_by_unit_answer_states_the_overhead_cost_and_share_as_the_report_does(
    api: httpx.Client, capsys: pytest.CaptureFixture[str]
) -> None:
    body = api.get("/api/usage", params={"by": "unit"}).json()

    assert body["overhead_cost_usd"] == pytest.approx(21.86)
    assert body["overhead_share"] == pytest.approx(21.86 / 354.0)
    capsys.readouterr()
    assert main(["report", "--by", "unit", "--json"]) == 0
    assert body == json.loads(capsys.readouterr().out)
