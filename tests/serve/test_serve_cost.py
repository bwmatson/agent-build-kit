"""The web UI's usage view and its local cost metric read each call's incremental figure and add
nothing for a call without one (spec: usage-reporting, Cost in every report, summary and metric
is the sum of incremental figures)."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from agent_build_kit.installation import Installation
from agent_build_kit.serve.server import create_app
from agent_build_kit.settings import reload
from tests.ledger_lines import costed_line, legacy_line, worked_session, write_ledger
from tests.serving import seed_pipeline


def test_the_usage_view_totals_the_session_increments(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    write_ledger(inst.state_dir / "usage-ledger.jsonl", *worked_session())

    body = api.get("/api/usage", params={"by": "unit"}).json()

    assert body["total"]["measured"]["cost_usd"] == pytest.approx(25.39)
    assert [s["session_id"] for s in body["sessions"]] == ["sess-worked"]
    assert body["sessions"][0]["cumulative_usd"] == pytest.approx(25.39)


def test_the_usage_view_keeps_legacy_rows_out_of_the_cost(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    write_ledger(
        inst.state_dir / "usage-ledger.jsonl",
        legacy_line(13.18, session_id="old"),
        costed_line(2.0, 2.0, basis="first", node="implement", session_id="new"),
    )

    body = api.get("/api/usage", params={"by": "unit"}).json()

    assert body["total"]["measured"]["cost_usd"] == pytest.approx(2.0)
    assert body["legacy"]["count"] == 1
    assert body["legacy"]["total_usd"] == pytest.approx(13.18)


def test_the_local_cost_metric_adds_incremental_figures_and_nothing_for_an_absent_one(
    inst: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ABK_PROMETHEUS_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("ABK_TEMPO_URL", "http://127.0.0.1:1")
    reload(None)
    write_ledger(
        inst.state_dir / "usage-ledger.jsonl",
        costed_line(1.5, 9.0, session_id="a", node="tests"),
        costed_line(2.25, 11.25, session_id="a", node="implement", resumed=True),
        costed_line(None, 7.0, basis="unknown", session_id="b", node="review"),
        legacy_line(40.0, session_id="old", node="rework"),
    )

    answer = TestClient(create_app(inst)).get("/api/metrics").json()

    cost = next(m for m in answer["metrics"] if m["name"] == "abk.agent.cost")
    assert answer["source"] == "local"
    assert sum(p[1] for s in cost["series"] for p in s["points"]) == pytest.approx(3.75)
