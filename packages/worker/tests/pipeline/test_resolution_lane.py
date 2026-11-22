"""The resolution lane, the restack lane under its new name: its worker thread is named
"resolve". The cap, the queue and the rest are held by `test_restack_lane.py`."""

from __future__ import annotations

import threading
from pathlib import Path

from agent_build_kit.pipeline.events import build_claim
from agent_build_kit.pipeline.resolution_lane import ResolutionLane
from agent_build_kit.pipeline.unit_store import StoredUnit
from tests.factories import stored_unit


def test_a_run_goes_on_a_thread_named_resolve(tmp_path: Path) -> None:
    names: list[str] = []

    def move(unit: StoredUnit) -> None:
        names.append(threading.current_thread().name)

    lane = ResolutionLane(2, move=move, claim=build_claim(tmp_path / "locks"))
    with lane:
        lane.hand_over(stored_unit("feature/1", change="feature"))
        lane.drain()

    assert names == ["resolve"]
