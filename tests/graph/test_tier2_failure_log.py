"""A failing tier 2 leaves the tail of its output in the unit's run log, with
the node's prefix, besides the words "tier 2 failed" (docs/unit-graph.md)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.unit import run_unit
from agent_build_kit.pipeline.run_log import RunLog
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.factories import unit
from tests.runner_fakes import Recorder, make_runner

FAILURE = "\n".join(
    [
        "## Tier 2 results",
        "FAILED tests/live/test_route.py::test_it - the route 404s",
        "1 failed, 3 passed",
    ]
)


def test_a_failing_tier_two_writes_the_tail_of_its_output_to_the_run_log(tmp_path: Path) -> None:
    logs = tmp_path / "unit-logs"
    tier_two = unit(tier="tier2")
    run_log = RunLog(
        logs, tier_two, step="build", model="m", base="main", started=datetime.now(UTC)
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert([tier_two])
    recorder = Recorder(store, tier2_ok=False)
    recorder.tier2_output = FAILURE
    runner = make_runner(store, recorder, tmp_path)

    async def go() -> None:
        async with open_checkpointer(unit_graphs_path(tmp_path / "state")) as saver:
            await run_unit(
                runner, tier_two, base="main", graph=[], saver=saver, run_log=run_log, tracer=None
            )

    asyncio.run(go())

    (written,) = logs.iterdir()
    lines = written.read_text().splitlines()
    assert any("tier2: stopping: tier 2 failed" in line for line in lines), "\n".join(lines)
    for output_line in FAILURE.splitlines():
        assert any("tier2:" in line and output_line in line for line in lines), (
            f"{output_line!r} is not in the run log:\n" + "\n".join(lines)
        )
