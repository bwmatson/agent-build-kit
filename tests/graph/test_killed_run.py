"""A run killed mid-node is resumed at that node by the next tick, and the
thread is what resumes it (docs/unit-graph.md, Durability)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.graph.state import Node
from agent_build_kit.pipeline.stack_runner import RunStatus
from tests.graph_driver import fresh, position, tick
from tests.runner_fakes import Killed

UNIT = "add-marker/1"


def test_a_run_killed_mid_node_is_resumed_at_that_node_and_never_requeued(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path, kill_after="commit:feat")
    with pytest.raises(Killed):
        tick(tmp_path, recorder)

    assert position(tmp_path).next == (Node.IMPLEMENT,)
    assert recorder.store.get(UNIT).state == "running", "nothing put it back to planned"

    outcome = tick(tmp_path, recorder)

    assert outcome.status == RunStatus.OPEN
    assert recorder.made == 2, "the implementation was committed once"
    assert recorder.events.count("claude:impl") == 1
    assert recorder.store.get(UNIT).state == "in_review"
