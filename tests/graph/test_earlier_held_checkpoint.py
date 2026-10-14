"""A checkpoint written before the held state was plain text still loads.

Those hold the `UnitState` enum in `hold_state`; the library reads it back as
its text, which the field accepts, and the unit is routed as before.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.state import UnitRun
from agent_build_kit.pipeline.units import PLANNED
from tests.checkpoint_types import blocked_while_reading
from tests.graph.checkpoint_reads import read_back, thread_config
from tests.graph.test_hold_causes import fresh, upstream_went_back


def with_the_enum_stored(db: Path) -> None:
    """Rewrite the thread's latest checkpoint as an earlier release wrote it."""

    async def rewrite() -> None:
        async with open_checkpointer(db) as saver:
            latest = await saver.aget_tuple(thread_config())
            assert latest is not None
            checkpoint = dict(latest.checkpoint)
            values: dict[str, Any] = latest.checkpoint["channel_values"]
            checkpoint["channel_values"] = {**values, "hold_state": PLANNED}
            await saver.aput(latest.config, checkpoint, latest.metadata, {})  # type: ignore[arg-type]

    asyncio.run(rewrite())


def test_a_checkpoint_holding_the_enum_loads_as_the_same_text_and_routes_as_before(
    tmp_path: Path,
) -> None:
    upstream_went_back(tmp_path, fresh(tmp_path))
    db = unit_graphs_path(tmp_path / "state")
    written_now = read_back(db)

    with_the_enum_stored(db)
    with blocked_while_reading() as blocked:
        earlier: Any = read_back(db)

    assert ("agent_build_kit.pipeline.units", "UnitState") in blocked
    loaded = UnitRun.model_validate(earlier.values)
    assert (loaded.hold_state, type(loaded.hold_state)) == (PLANNED.value, str)
    assert earlier.next == written_now.next
    assert earlier.values["held"] == written_now.values["held"]
