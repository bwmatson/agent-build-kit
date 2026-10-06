"""A unit's agent calls are attributed from the gateway's own records for a key
minted for each (spec: gateway-usage-attribution).

The gateway is `tests/fake_gateway.py`, a real HTTP server speaking a gateway's
JSON, and the agent is a runtime that plays model traffic against it with
whatever key it was handed, so what the ledger holds can only have come from
the gateway's logs for that key.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.gateway_usage import KEY_ENV
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.wiring import build_run_claude
from agent_build_kit.runtimes import AgentRequest, AgentResult
from agent_build_kit.settings import settings
from agent_build_kit.usage import Usage
from tests.fake_gateway import MASTER, FakeGateway, answering_garbage, serving, unreachable_url
from tests.graph_driver import fresh, tick
from tests.runtimes.stand_in import StandInRuntime


class Modelled(StandInRuntime):
    """An agent that reads its key from its environment and spends through it:
    call n makes one request of 1000n prompt and 100n completion tokens, costing
    0.5n, through the gateway, then answers with `reported` as what it says it
    spent."""

    name = "modelled"
    passes_env = True

    def __init__(
        self,
        gateway: FakeGateway | None,
        *,
        reported: Usage | None = None,
        reported_cost: float | None = None,
        ok: bool = True,
        raises: bool = False,
    ) -> None:
        super().__init__(answer="done", ok=ok, error="" if ok else "it went wrong")
        self.gateway = gateway
        self.reported = reported
        self.reported_cost = reported_cost
        self.raises = raises

    def run(self, request: AgentRequest) -> AgentResult:
        self.requests.append(request)
        n = len(self.requests)
        key = request.env.get(KEY_ENV)
        if key and self.gateway is not None:
            self.gateway.spend(key, prompt=1000 * n, completion=100 * n, cost=0.5 * n)
        if self.raises:
            raise RuntimeError("the agent fell over")
        result = AgentResult(
            ok=self.ok,
            text="done",
            error=self.error,
            usage=self.reported,
            cost_usd=self.reported_cost,
            usage_source="reported" if self.reported or self.reported_cost else "none",
        )
        if request.on_result is not None:
            request.on_result(result)
        return result


@pytest.fixture
def gateway(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeGateway]:
    with serving() as fake:
        monkeypatch.setattr(settings, "gateway_url", fake.url)
        monkeypatch.setattr(settings, "gateway_master_key", MASTER)
        monkeypatch.setattr(settings, "gateway_settle_seconds", 0.1)
        yield fake


def ledger(workspace: Installation) -> dict[str, dict]:
    """The agent calls of the unit's build, by node."""
    path = workspace.state_dir / "usage-ledger.jsonl"
    lines = [json.loads(line) for line in path.read_text().splitlines() if line]
    return {line["node"]: line for line in lines if line.get("kind", "agent") == "agent"}


def build(tmp_path: Path, runtime: Modelled, lines: list[str]) -> RunStatus:
    return tick(
        tmp_path,
        fresh(tmp_path),
        run_claude=build_run_claude(runtime=runtime, model="m", log=lines.append),
    ).status


def test_a_run_gets_a_key_named_for_its_place_and_records_the_gateways_totals(
    tmp_path: Path, workspace: Installation, gateway: FakeGateway
) -> None:
    runtime = Modelled(gateway)

    status = build(tmp_path, runtime, [])

    assert status == RunStatus.OPEN
    first, second = gateway.minted
    assert all(m["auth"] == f"Bearer {MASTER}" for m in gateway.minted)
    assert first["alias"].startswith("abk:add-marker/1:tests:0:")
    assert second["alias"].startswith("abk:add-marker/1:implement:0:")
    assert first["alias"] != second["alias"]
    assert [r.env[KEY_ENV] for r in runtime.requests] == [first["key"], second["key"]]

    records = ledger(workspace)
    assert records["tests"]["usage_source"] == "gateway"
    assert records["tests"]["input_tokens"] == 1000
    assert records["tests"]["output_tokens"] == 100
    assert records["tests"]["cost_usd"] == 0.5
    assert records["implement"]["usage_source"] == "gateway"
    assert records["implement"]["input_tokens"] == 2000
    assert records["implement"]["output_tokens"] == 200
    assert records["implement"]["cost_usd"] == 1.0
    assert gateway.revoked == [first["key"], second["key"]]


@pytest.mark.parametrize("how", ["a failed result", "an exception"])
def test_the_key_is_revoked_even_when_the_run_fails(
    how: str, tmp_path: Path, gateway: FakeGateway
) -> None:
    runtime = Modelled(gateway, ok=how != "a failed result", raises=how == "an exception")

    with contextlib.suppress(Exception):
        build(tmp_path, runtime, [])

    assert len(gateway.minted) >= 1
    assert gateway.revoked == [m["key"] for m in gateway.minted]


def test_a_failed_call_still_records_what_the_gateway_logged(
    tmp_path: Path, workspace: Installation, gateway: FakeGateway
) -> None:
    with contextlib.suppress(Exception):
        build(tmp_path, Modelled(gateway, ok=False), [])

    (record,) = ledger(workspace).values()
    assert record["outcome"] == "failed"
    assert record["usage_source"] == "gateway"
    assert record["input_tokens"] == 1000


def test_what_the_agent_reports_is_kept_beside_the_gateways_figures(
    tmp_path: Path, workspace: Installation, gateway: FakeGateway
) -> None:
    runtime = Modelled(
        gateway, reported=Usage(input_tokens=900, output_tokens=90), reported_cost=0.4
    )

    build(tmp_path, runtime, [])

    record = ledger(workspace)["tests"]
    assert record["usage_source"] == "gateway"
    assert (record["input_tokens"], record["output_tokens"], record["cost_usd"]) == (1000, 100, 0.5)
    assert record["reported"]["input_tokens"] == 900
    assert record["reported"]["output_tokens"] == 90
    assert record["reported_cost_usd"] == 0.4


def test_an_agent_that_reports_nothing_leaves_nothing_beside_the_gateways_figures(
    tmp_path: Path, workspace: Installation, gateway: FakeGateway
) -> None:
    build(tmp_path, Modelled(gateway), [])

    record = ledger(workspace)["tests"]
    assert record["usage_source"] == "gateway"
    assert record["reported"] is None
    assert record["reported_cost_usd"] is None


def test_an_agent_that_never_spends_through_its_key_keeps_its_own_figures(
    tmp_path: Path, workspace: Installation, gateway: FakeGateway
) -> None:
    class Silent(Modelled):
        def run(self, request: AgentRequest) -> AgentResult:
            request = request.model_copy(update={"env": {}})
            return super().run(request)

    runtime = Silent(gateway, reported=Usage(input_tokens=900, output_tokens=90), reported_cost=0.4)

    build(tmp_path, runtime, [])

    record = ledger(workspace)["tests"]
    assert record["usage_source"] == "reported"
    assert record["input_tokens"] == 900
    assert record["reported"] is None
    assert gateway.revoked == [m["key"] for m in gateway.minted]


def test_a_runtime_that_cannot_pass_env_is_skipped_with_a_line(
    tmp_path: Path, workspace: Installation, gateway: FakeGateway
) -> None:
    class NoEnv(Modelled):
        name = "no-env"
        passes_env = False

    runtime = NoEnv(gateway, reported=Usage(input_tokens=900, output_tokens=90))
    lines: list[str] = []

    build(tmp_path, runtime, lines)

    assert gateway.calls == []
    assert all(KEY_ENV not in r.env for r in runtime.requests)
    skips = [line for line in lines if "no-env" in line and "skipped" in line]
    assert len(skips) == len(runtime.requests)
    record = ledger(workspace)["tests"]
    assert record["usage_source"] == "reported"
    assert record["input_tokens"] == 900


def test_an_unreachable_gateway_leaves_the_run_unchanged_and_warns_once_per_run(
    tmp_path: Path,
    workspace: Installation,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "gateway_url", unreachable_url())
    monkeypatch.setattr(settings, "gateway_master_key", MASTER)
    runtime = Modelled(None, reported=Usage(input_tokens=900, output_tokens=90))
    lines: list[str] = []

    status = build(tmp_path, runtime, lines)

    assert status == RunStatus.OPEN
    assert all(KEY_ENV not in r.env for r in runtime.requests)
    warnings = [line for line in lines if "gateway" in line.lower()]
    assert len(warnings) == len(runtime.requests)
    record = ledger(workspace)["tests"]
    assert record["usage_source"] == "reported"
    assert record["input_tokens"] == 900


def test_a_refused_mint_leaves_the_run_unchanged_and_warns_once_per_run(
    tmp_path: Path, workspace: Installation, gateway: FakeGateway
) -> None:
    gateway.refuse_mint = True
    runtime = Modelled(gateway)
    lines: list[str] = []

    status = build(tmp_path, runtime, lines)

    assert status == RunStatus.OPEN
    assert all(KEY_ENV not in r.env for r in runtime.requests)
    warnings = [line for line in lines if "gateway" in line.lower()]
    assert len(warnings) == len(runtime.requests)
    assert ledger(workspace)["tests"]["usage_source"] == "none"
    assert gateway.revoked == []


def test_a_gateway_that_cannot_be_read_falls_back_and_still_revokes_the_key(
    tmp_path: Path, workspace: Installation, gateway: FakeGateway
) -> None:
    gateway.fail_reads = True
    runtime = Modelled(gateway, reported=Usage(input_tokens=900, output_tokens=90))
    lines: list[str] = []

    status = build(tmp_path, runtime, lines)

    assert status == RunStatus.OPEN
    record = ledger(workspace)["tests"]
    assert record["usage_source"] == "reported"
    assert record["input_tokens"] == 900
    assert gateway.revoked == [m["key"] for m in gateway.minted]
    warnings = [line for line in lines if "gateway" in line.lower()]
    assert len(warnings) == len(runtime.requests)


def test_a_gateway_that_speaks_garbage_leaves_the_run_status_unchanged(
    tmp_path: Path, workspace: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    with answering_garbage() as url:
        monkeypatch.setattr(settings, "gateway_url", url)
        monkeypatch.setattr(settings, "gateway_master_key", MASTER)
        runtime = Modelled(None, reported=Usage(input_tokens=900, output_tokens=90))
        lines: list[str] = []

        status = build(tmp_path, runtime, lines)

    assert status == RunStatus.OPEN
    assert all(KEY_ENV not in r.env for r in runtime.requests)
    assert ledger(workspace)["tests"]["usage_source"] == "reported"
