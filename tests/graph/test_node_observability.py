"""A node's progress reaches the unit's run log, and each node is a span
carrying the unit id (docs/unit-graph.md, Observability)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.state import Node
from agent_build_kit.graph.unit import run_unit
from agent_build_kit.pipeline.run_log import RunLog
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.factories import unit
from tests.runner_fakes import Recorder, make_runner

BUILD_PATH = (
    "prepare",
    "tests",
    "implement",
    "checks",
    "review",
    "verify_base",
    "push",
    "open_pr",
    "await_review",
)


class FakeTracer:
    """An OpenTelemetry tracer's `start_as_current_span`, recording each span."""

    def __init__(self) -> None:
        self.spans: list[tuple[str, dict[str, str]]] = []

    @contextmanager
    def start_as_current_span(
        self, name: str, *, attributes: Mapping[str, str] | None = None
    ) -> Iterator[None]:
        self.spans.append((name, dict(attributes or {})))
        yield


def run(
    tmp_path: Path, *, run_log: RunLog | None, tracer: FakeTracer | None, **options: Any
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder(store)
    runner = make_runner(store, recorder, tmp_path, **options)

    async def go() -> None:
        async with open_checkpointer(unit_graphs_path(tmp_path / "state")) as saver:
            await run_unit(
                runner, unit(), base="main", graph=[], saver=saver, run_log=run_log, tracer=tracer
            )

    asyncio.run(go())


def test_each_nodes_progress_lines_reach_the_units_run_log(tmp_path: Path) -> None:
    logs = tmp_path / "unit-logs"
    run_log = RunLog(logs, unit(), step="build", model="m", base="main", started=datetime.now(UTC))

    run(tmp_path, run_log=run_log, tracer=None)

    (written,) = logs.iterdir()
    lines = written.read_text().splitlines()
    for node in BUILD_PATH:
        assert any(node in line for line in lines), f"nothing from {node} in the run log"


def test_a_usage_pause_says_why_in_the_units_run_log(tmp_path: Path) -> None:
    logs = tmp_path / "unit-logs"
    run_log = RunLog(logs, unit(), step="build", model="m", base="main", started=datetime.now(UTC))

    run(tmp_path, run_log=run_log, tracer=None, may_start=lambda: (False, "session usage at 88%"))

    (written,) = logs.iterdir()
    assert "paused before the agent step: session usage at 88%" in written.read_text()


def test_each_node_is_a_span_carrying_the_unit_id_change_and_step(tmp_path: Path) -> None:
    tracer = FakeTracer()

    run(tmp_path, run_log=None, tracer=tracer)

    names = [name for name, _ in tracer.spans]
    assert [n for n in names if n in {node.value for node in Node}] == list(BUILD_PATH)
    for _, attributes in tracer.spans:
        assert attributes["unit"] == "add-marker/1"
        assert attributes["change"] == "add-marker"
    assert {a["step"] for _, a in tracer.spans} == set(BUILD_PATH)
