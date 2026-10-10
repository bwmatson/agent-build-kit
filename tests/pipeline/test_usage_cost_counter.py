"""The cost counter is raised by a call's incremental figure, and by nothing when there is none
(spec: usage-telemetry-rollup, Cost in every report, summary and metric is the sum of
incremental figures).

The receiver is an in-process OTLP/HTTP server decoding the bodies the real exporter posts.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from agent_build_kit import telemetry
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.usage_ledger import UsageRecord, forget_told, record_call
from tests.ledger_lines import costed_line, legacy_line
from tests.otlp import Collector, enabled


@pytest.fixture(autouse=True)
def _fresh_notices() -> None:
    forget_told()


@pytest.fixture
def exported() -> Iterator[Collector]:
    with enabled() as collector:
        assert telemetry.init() is True
        yield collector


def record(line: dict) -> None:
    record_call(UsageRecord.model_validate(line), print)


def test_a_call_raises_the_counter_by_its_incremental_figure_and_not_its_running_total(
    workspace: Installation, exported: Collector
) -> None:
    record(costed_line(2.86, 5.49))
    telemetry.shutdown()

    (cost,) = exported.metric("abk.agent.cost")
    assert cost.value == pytest.approx(2.86)


def test_a_call_with_no_incremental_figure_adds_nothing(
    workspace: Installation, exported: Collector
) -> None:
    record(costed_line(1.25, 1.25, basis="first", session_id="a"))
    record(costed_line(None, 5.49, basis="unknown", session_id="b"))
    telemetry.shutdown()

    (cost,) = exported.metric("abk.agent.cost")
    assert cost.value == pytest.approx(1.25)


def test_a_legacy_line_adds_nothing(workspace: Installation, exported: Collector) -> None:
    record(legacy_line(13.18))
    telemetry.shutdown()

    assert exported.metric("abk.agent.cost") == []
