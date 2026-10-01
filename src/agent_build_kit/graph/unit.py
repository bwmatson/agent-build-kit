"""Running one unit's build path through its thread."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractContextManager
from typing import Protocol

from langgraph.checkpoint.base import BaseCheckpointSaver

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
    raise NotImplementedError
