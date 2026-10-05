"""A run killed mid-node is resumed at that node by the next tick, and the
classic requeue to `planned` leaves a unit that has a thread alone
(docs/unit-graph.md, Durability; Moving the units in flight)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.graph.state import Node
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.settings import settings
from tests.conftest import make_installation
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


def test_the_ticks_reclaim_leaves_a_running_unit_that_has_a_thread_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On the graph engine the thread is what resumes the unit: `reclaim_stale`
    would requeue it to `planned` and commit its leftovers as feedback, which
    the thread's own node does on its re-run."""
    inst = make_installation(tmp_path, planning={"state_dir": "state"})
    monkeypatch.setattr(settings, "engine", "graph")
    recorder = fresh(tmp_path, kill_after="commit:feat")
    with pytest.raises(Killed):
        tick(tmp_path, recorder)
    committed: list[str] = []
    monkeypatch.setattr(cli, "commit_leftovers", lambda inst, unit: committed.append(unit.id) or 0)

    cli.reclaim_stale(inst, store=recorder.store)

    stored = recorder.store.get(UNIT)
    assert stored.state == "running"
    assert not any("reclaimed" in str(entry) for entry in stored.history)
    assert committed == []
