"""What the recorder that writes a ledger line also exports as metrics: cost,
tokens by kind, node and wait durations, with bounded attributes and never a
unit id or change name; measured and estimated figures stay apart, and with
telemetry off nothing is exported (spec: usage-telemetry-rollup).

The receiver is an in-process OTLP/HTTP server decoding the bodies the real
exporter posts.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from agent_build_kit import telemetry
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.spans import Mark, record_span
from agent_build_kit.pipeline.usage_ledger import (
    LEDGER_NAME,
    UsageRecord,
    forget_told,
    read_ledger,
    record_call,
)
from tests import fake_clock
from tests.ledger_lines import agent_line
from tests.otlp import Collector, Point, enabled

BOUNDED = {"repo", "tier", "node", "role", "model", "bucket", "source", "kind"}
USAGE_METRICS = ("abk.agent.cost", "abk.agent.tokens", "abk.node.duration", "abk.wait.duration")


@pytest.fixture(autouse=True)
def _fresh_notices() -> None:
    forget_told()


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> fake_clock.FakeClock:
    return fake_clock.install(monkeypatch)


@pytest.fixture
def exported() -> Iterator[Collector]:
    with enabled() as collector:
        assert telemetry.init() is True
        yield collector


def usage_points(collector: Collector) -> list[Point]:
    return [point for name in USAGE_METRICS for point in collector.metric(name)]


def record_agent(**fields: object) -> None:
    record_call(UsageRecord.model_validate(agent_line(**fields)), print)


def record_span_of(
    seconds: float, node: str = "implement", waited: str = "", command: str = ""
) -> None:
    """A span of `seconds`, written through the same recorder a node's run uses."""
    mark = Mark()
    spans.clock.advance(seconds)  # type: ignore[attr-defined]
    record_span(
        mark,
        print,
        unit="add-marker/7",
        change="add-marker",
        node=node,
        waited=waited,
        command=command,
    )


def exported_tokens(collector: Collector) -> list[Point]:
    """The ledger's token points: they carry a source, the runtime's own do not."""
    return [p for p in collector.metric("abk.agent.tokens") if "source" in p.attributes]


def test_an_agent_record_adds_its_cost_and_tokens_by_role_and_model(
    workspace: Installation, exported: Collector
) -> None:
    record_agent(usage_source="gateway")
    telemetry.shutdown()

    (cost,) = exported.metric("abk.agent.cost")
    assert cost.value == 1.0
    assert cost.attributes == {
        "repo": "app",
        "tier": "tier1",
        "node": "implement",
        "role": "implement",
        "model": "model-a",
        "source": "measured",
    }
    tokens = {point.attributes["kind"]: point for point in exported_tokens(exported)}
    assert {kind: point.value for kind, point in tokens.items()} == {
        "input": 100,
        "output": 50,
        "cache_read": 1000,
        "cache_creation": 200,
    }
    for point in tokens.values():
        assert point.attributes["role"] == "implement"
        assert point.attributes["model"] == "model-a"


def test_a_work_span_adds_node_duration_in_seconds(
    workspace: Installation, exported: Collector
) -> None:
    record_span_of(1.5, node="review")
    telemetry.shutdown()

    (point,) = exported.metric("abk.node.duration")
    assert point.attributes["node"] == "review"
    assert (point.count, point.value) == (1, 1.5)
    assert exported.metric("abk.wait.duration") == []


def test_a_wait_span_adds_wait_duration_under_its_bucket(
    workspace: Installation, exported: Collector
) -> None:
    record_span_of(90, waited="slot")
    record_span_of(30, waited="usage_pause")
    telemetry.shutdown()

    waits = {point.attributes["bucket"]: point for point in exported.metric("abk.wait.duration")}
    assert {bucket: point.value for bucket, point in waits.items()} == {
        "slot": 90,
        "usage_pause": 30,
    }
    assert exported.metric("abk.node.duration") == []


def test_no_metric_attribute_holds_a_unit_id_or_change_name_or_is_unbounded(
    workspace: Installation, exported: Collector
) -> None:
    record_agent(unit="add-marker/7", change="add-marker", session_id="sess-secret")
    record_span_of(2, node="implement")
    record_span_of(3, waited="slot")
    telemetry.shutdown()

    points = usage_points(exported)
    assert points
    for point in points:
        assert set(point.attributes) <= BOUNDED, point
        values = [str(value) for value in point.attributes.values()]
        assert not [v for v in values if "add-marker" in v or "sess-secret" in v], point


def test_measured_and_estimated_figures_are_separate_series(
    workspace: Installation, exported: Collector
) -> None:
    record_agent(session_id="s-1", usage_source="gateway", cost_usd=1.0)
    record_agent(session_id="s-2", usage_source="reported", cost_usd=2.0)
    record_agent(session_id="s-3", usage_source="estimated", cost_usd=0.25)
    telemetry.shutdown()

    by_source = {
        point.attributes["source"]: point.value for point in exported.metric("abk.agent.cost")
    }
    assert by_source == {"measured": 3.0, "estimated": 0.25}


def test_a_figure_the_record_does_not_have_adds_nothing(
    workspace: Installation, exported: Collector
) -> None:
    record_agent(
        cost_usd=None,
        input_tokens=None,
        output_tokens=None,
        cache_read_input_tokens=None,
        cache_creation_input_tokens=None,
        usage_source="none",
    )
    telemetry.shutdown()

    assert exported.metric("abk.agent.cost") == []
    assert exported_tokens(exported) == []


def test_with_telemetry_off_the_ledger_is_written_and_nothing_is_exported(
    workspace: Installation,
) -> None:
    with enabled() as collector:
        # enabled() configures the endpoint; nothing has initialised telemetry yet.
        record_agent(session_id="off-1")
        record_span_of(5, waited="slot")
        telemetry.shutdown()
        assert collector.posts == []

        # The same records with telemetry on are exported, so the silence above
        # is the switch and not an absent feature.
        assert telemetry.init() is True
        record_agent(session_id="on-1")
        telemetry.shutdown()
        assert collector.metric("abk.agent.cost")

    ledger = workspace.state_dir / LEDGER_NAME
    assert len(ledger.read_text().splitlines()) == 3
    assert {r.session_id for r in read_ledger(ledger)} == {"off-1", "on-1"}


def test_a_tier_1_command_span_adds_no_time_of_its_own(
    workspace: Installation, exported: Collector
) -> None:
    record_span_of(2.0, node="implement", command="test")
    telemetry.shutdown()

    assert exported.metric("abk.node.duration") == []
    assert exported.metric("abk.wait.duration") == []


def test_an_agent_record_with_no_model_is_labelled_default(
    workspace: Installation, exported: Collector
) -> None:
    record_agent(usage_source="gateway", model="")
    telemetry.shutdown()

    assert {p.attributes["model"] for p in exported_tokens(exported)} == {"default"}
