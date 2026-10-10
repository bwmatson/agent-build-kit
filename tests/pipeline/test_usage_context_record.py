"""A ledger line carries a `context` object, read tolerantly; a call's context figures are
exported as gauges and a counter with the cost's bounded attributes; a step that ends near the
limit logs one warning and nothing more (spec: usage-accounting, Every agent call records its
context window use in tokens; usage-reporting, The report shows context use per step and per
session).

The receiver is an in-process OTLP/HTTP server decoding the bodies the real exporter posts.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import telemetry
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.usage_ledger import (
    UsageRecord,
    forget_told,
    read_ledger,
    record_call,
)
from agent_build_kit.usage import ContextBasis
from tests.conftest import make_installation
from tests.ledger_lines import agent_line, context_line, write_ledger
from tests.otlp import Collector, enabled

K = 1000


@pytest.fixture(autouse=True)
def _fresh_notices() -> None:
    forget_told()


@pytest.fixture
def exported() -> Iterator[Collector]:
    with enabled() as collector:
        assert telemetry.init() is True
        yield collector


def record(line: dict, said: list[str] | None = None) -> None:
    record_call(UsageRecord.model_validate(line), (said if said is not None else []).append)


# --- the line --------------------------------------------------------------------------


def test_a_line_with_a_context_object_is_read_with_its_figures(tmp_path: Path) -> None:
    ledger = write_ledger(
        tmp_path / "usage-ledger.jsonl",
        context_line(150 * K, 80 * K, peak=195 * K, compactions=1, window=200 * K),
    )

    (read,) = read_ledger(ledger)

    assert read.context is not None
    assert read.context.used_start == 150 * K
    assert read.context.used_end == 80 * K
    assert read.context.added == 0
    assert read.context.peak == 195 * K
    assert read.context.compactions == 1
    assert read.context.max == 200 * K
    assert read.context.basis == ContextBasis.REPORTED


def test_a_line_written_before_context_was_recorded_has_none(tmp_path: Path) -> None:
    ledger = write_ledger(tmp_path / "usage-ledger.jsonl", agent_line())

    (read,) = read_ledger(ledger)

    assert read.context is None


def test_a_figure_of_the_wrong_type_reads_as_absent_and_the_line_still_loads(
    tmp_path: Path,
) -> None:
    line = context_line(1, 2) | {
        "context": {"used_end": "lots", "max": [200], "peak": True, "basis": "reported"}
    }
    ledger = write_ledger(tmp_path / "usage-ledger.jsonl", line)

    (read,) = read_ledger(ledger)

    assert read.context is not None
    assert read.context.used_end is None
    assert read.context.max is None


def test_a_context_that_is_not_an_object_is_absent(tmp_path: Path) -> None:
    ledger = write_ledger(tmp_path / "usage-ledger.jsonl", agent_line() | {"context": "full"})

    (read,) = read_ledger(ledger)

    assert read.context is None


# --- the warning -----------------------------------------------------------------------


def test_a_step_ending_above_the_warning_share_logs_one_warning(workspace: Installation) -> None:
    said: list[str] = []

    record(context_line(150 * K, 170 * K, window=200 * K), said)

    warned = [line for line in said if "context" in line.lower()]
    assert len(warned) == 1
    assert "170" in warned[0] and "200" in warned[0]


def test_a_step_ending_below_it_logs_nothing(workspace: Installation) -> None:
    said: list[str] = []

    record(context_line(50 * K, 100 * K, window=200 * K), said)

    assert said == []


def test_the_share_that_warns_is_configured(tmp_path: Path) -> None:
    make_installation(tmp_path / "planning", context={"warn_share": 0.4})
    said: list[str] = []

    record(context_line(50 * K, 100 * K, window=200 * K), said)

    assert len([line for line in said if "context" in line.lower()]) == 1


def test_a_step_whose_window_is_unknown_cannot_warn(workspace: Installation) -> None:
    said: list[str] = []

    record(context_line(150 * K, 190 * K, window=None, basis="unknown"), said)

    assert said == []


def test_a_warning_still_leaves_the_record_in_the_ledger(workspace: Installation) -> None:
    record(context_line(150 * K, 190 * K, window=200 * K))

    (read,) = read_ledger(workspace.state_dir / "usage-ledger.jsonl")
    assert read.context is not None
    assert read.context.used_end == 190 * K


# --- the metrics -----------------------------------------------------------------------


def test_a_call_exports_its_fill_and_window_as_gauges(
    workspace: Installation, exported: Collector
) -> None:
    record(context_line(100 * K, 142 * K, window=200 * K))
    telemetry.shutdown()

    (used,) = exported.metric("abk.agent.context_used")
    (limit,) = exported.metric("abk.agent.context_max")
    assert used.value == 142 * K
    assert limit.value == 200 * K


def test_the_gauges_carry_the_costs_bounded_attributes_and_no_unit_or_session(
    workspace: Installation, exported: Collector
) -> None:
    record(context_line(100 * K, 142 * K, window=200 * K))
    telemetry.shutdown()

    (cost,) = exported.metric("abk.agent.cost")
    for name in ("abk.agent.context_used", "abk.agent.context_max"):
        (point,) = exported.metric(name)
        assert point.attributes == cost.attributes
        assert not {"unit", "change", "session_id"} & set(point.attributes)


def test_compactions_raise_the_counter_by_the_calls_count(
    workspace: Installation, exported: Collector
) -> None:
    record(context_line(150 * K, 80 * K, peak=195 * K, compactions=2, window=200 * K))
    telemetry.shutdown()

    (compactions,) = exported.metric("abk.agent.compactions")
    assert compactions.value == 2


def test_a_call_with_no_context_figures_exports_nothing(
    workspace: Installation, exported: Collector
) -> None:
    record(agent_line())
    record(context_line(None, None, window=None, basis="unknown", session_id="b"))
    telemetry.shutdown()

    assert exported.metric("abk.agent.context_used") == []
    assert exported.metric("abk.agent.context_max") == []
    assert exported.metric("abk.agent.compactions") == []
