"""Drives a unit's thread the way the engine does: one call per tick, each on a
new connection to the same checkpoint file, as a new process has."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.state import ResumeEvent
from agent_build_kit.graph.unit import Position, resume_unit, run_unit, thread_position
from agent_build_kit.pipeline.run_log import RunLog
from agent_build_kit.pipeline.stack_runner import RunOutcome, UnitRunner
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import Unit, branch_name
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.factories import unit
from tests.runner_fakes import Recorder, make_runner


class FakeTracer:
    """An OpenTelemetry tracer's `start_as_current_span`, recording each span's name."""

    def __init__(self) -> None:
        self.names: list[str] = []

    @contextmanager
    def start_as_current_span(
        self,
        name: str,
        *,
        attributes: Mapping[str, str | int] | None = None,
        record_exception: bool = True,
        set_status_on_exception: bool = True,
    ) -> Iterator[None]:
        self.names.append(name)
        yield


def fresh(tmp_path: Path, **options: Any) -> Recorder:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    return Recorder(store, **options)


def tick(
    tmp_path: Path,
    recorder: Recorder,
    *,
    event: ResumeEvent | None = None,
    tracer: FakeTracer | None = None,
    run_log: RunLog | None = None,
    **overrides: Any,
) -> RunOutcome:
    """Start or resume the unit's thread, or deliver `event` to it, as the
    tick does: a run under the branch's lock (`build_graph`'s), a delivery
    taking it itself."""
    runner = make_runner(recorder.store, recorder, tmp_path, **overrides)
    common: dict[str, Any] = dict(base="main", graph=[], run_log=run_log, tracer=tracer)
    locks = tmp_path / "locks"

    async def go() -> RunOutcome:
        async with open_checkpointer(unit_graphs_path(tmp_path / "state")) as saver:
            if event is None:
                with branch_lock(branch_name(unit()), root=locks):
                    return await run_unit(runner, unit(), saver=saver, **common)
            return await resume_unit(
                runner, unit(), saver=saver, event=event, locks=locks, **common
            )

    return asyncio.run(go())


def position(tmp_path: Path) -> Position:
    async def go() -> Position:
        async with open_checkpointer(unit_graphs_path(tmp_path / "state")) as saver:
            return await thread_position(saver, unit().id)

    return asyncio.run(go())


def run_on_graph(
    runner: UnitRunner,
    run_unit_of: Unit,
    *,
    base: str = "main",
    graph: list[StoredUnit] | None = None,
) -> RunOutcome:
    """Run a unit's thread over `runner`'s callables, as a tick does, with the
    thread's checkpoint and locks beside the runner's store."""
    where = runner.store.path.parent
    locks = where / "locks"

    async def go() -> RunOutcome:
        async with open_checkpointer(unit_graphs_path(where / "state")) as saver:
            with branch_lock(branch_name(run_unit_of), root=locks):
                return await run_unit(
                    runner, run_unit_of, base=base, graph=graph or [], saver=saver, tracer=None
                )

    return asyncio.run(go())
