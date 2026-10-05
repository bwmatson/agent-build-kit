"""Running one unit's build path through its thread."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractContextManager
from typing import Protocol

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver

from agent_build_kit.graph.build import compile_build_path
from agent_build_kit.graph.nodes import BuildPath
from agent_build_kit.graph.run import run_thread
from agent_build_kit.graph.state import UnitRun
from agent_build_kit.pipeline.run_log import RunLog
from agent_build_kit.pipeline.stack_runner import RunOutcome, UnitRunner
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import Unit


class Tracer(Protocol):
    """The part of an OpenTelemetry tracer a node's span uses."""

    def start_as_current_span(
        self, name: str, *, attributes: Mapping[str, str] | None = None
    ) -> AbstractContextManager[object]: ...


async def run_unit(
    runner: UnitRunner,
    unit: Unit,
    *,
    base: str,
    graph: list[StoredUnit],
    saver: BaseCheckpointSaver,
    run_log: RunLog | None = None,
    tracer: Tracer | None = None,
) -> RunOutcome:
    """Start the unit's thread, or resume it where a killed run left it, over
    the callables `runner` carries, and return what `UnitRunner.run` would."""
    path = BuildPath(runner, unit, base=base, graph=graph, run_log=run_log, tracer=tracer)
    compiled = compile_build_path(saver, path.work())
    config: RunnableConfig = {"configurable": {"thread_id": unit.id}}
    # A thread with a node still to run was interrupted: it carries on from
    # there, with no new input. Anything else is a new run of the unit.
    interrupted = bool((await compiled.aget_state(config)).next)
    # The whole state, not the fields set: a pydantic input writes only those,
    # and the previous run's verdict, pr and event would carry over.
    start = (
        None
        if interrupted
        else UnitRun(unit_id=unit.id, change=unit.change, groups=unit.groups).model_dump()
    )
    state = UnitRun.model_validate(await run_thread(compiled, start, unit.id))
    if state.status is None:
        raise RuntimeError(f"the thread for {unit.id} ended without a status")
    return RunOutcome(status=state.status, detail=state.detail, pr=state.pr)
