"""A thread saved before the e2e fields were renamed still routes through e2e-test.

The earlier release kept the flag and its ran-none field under their pre-rename names; the
library reads a checkpoint only through the channels the current schema declares, so those
values are gone when the thread is read back. A delivered event sets the flag again from the
unit's kind.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.state import EventKind, Node, ResumeEvent
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.factories import unit
from tests.graph.checkpoint_reads import a_config
from tests.graph_driver import position, tick
from tests.runner_fakes import Recorder

THREAD = unit().id
OLD_FLAG = "tier" + "2"  # the channel the earlier release kept the e2e flag in


def saved_under_the_old_field_names(db: Path) -> None:
    """Rewrite the thread's latest checkpoint as the earlier release wrote it."""

    async def rewrite() -> None:
        async with open_checkpointer(db) as saver:
            latest = await saver.aget_tuple(a_config(THREAD))
            assert latest is not None
            checkpoint = dict(latest.checkpoint)
            values: dict[str, Any] = dict(latest.checkpoint["channel_values"])
            assert values.pop("e2e") is True
            values.pop("e2e_ran_none", None)
            checkpoint["channel_values"] = {**values, OLD_FLAG: True, f"{OLD_FLAG}_ran_none": False}
            await saver.aput(latest.config, checkpoint, latest.metadata, {})  # type: ignore[arg-type]

    asyncio.run(rewrite())


def test_a_rework_of_an_e2e_test_unit_saved_under_the_old_field_names_runs_e2e_test(
    tmp_path: Path,
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(tier="e2e-test")])
    recorder = Recorder(store)
    tick(tmp_path, recorder, tier="e2e-test")
    assert position(tmp_path).next == (Node.AWAIT_REVIEW,)
    saved_under_the_old_field_names(unit_graphs_path(tmp_path / "state"))
    ran = len(recorder.events)

    tick(
        tmp_path,
        recorder,
        tier="e2e-test",
        event=ResumeEvent(kind=EventKind.REWORK, feedback="rename it"),
    )
    tick(tmp_path, recorder, tier="e2e-test")

    after = recorder.events[ran:]
    assert "e2e-test" in after, after
    assert position(tmp_path).next == (Node.AWAIT_REVIEW,)
