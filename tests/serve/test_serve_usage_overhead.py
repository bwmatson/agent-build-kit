"""The usage endpoint carries the pipeline overhead the report shows: one row per node for the calls
made with no unit, the same as `abk report --json` prints (spec: web-ui, every agent call is
recorded)."""

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
        agent_line(unit="feature/1", change="feature"),
        agent_line(node="restack", unit="feature/1", change="feature", role="generic"),
        agent_line(**OVERHEAD, node="plan", change="feature", cost_usd=0.25),
        agent_line(**OVERHEAD, node="chat", change="", cost_usd=0.125),
    )


@pytest.mark.usefixtures("ledger")
def test_the_by_unit_answer_has_a_line_per_overhead_node_and_equals_the_reports(
    api: httpx.Client, capsys: pytest.CaptureFixture[str]
) -> None:
    body = api.get("/api/usage", params={"by": "unit"}).json()

    assert [row["key"] for row in body["overhead"]] == ["chat", "plan"]
    assert "restack" not in {row["key"] for row in body["overhead"]}
    assert [row["key"] for row in body["rows"]] == ["feature/1"]
    capsys.readouterr()
    assert main(["report", "--by", "unit", "--json"]) == 0
    assert body == json.loads(capsys.readouterr().out)
