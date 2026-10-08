"""The graph is the only engine: a tick runs every unit on its thread."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.state import Node
from agent_build_kit.graph.unit import thread_position
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.events import Review
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, RUNNING
from agent_build_kit.pipeline.usage_guard import Decision
from tests.conftest import make_installation
from tests.graph_driver import fresh
from tests.runner_fakes import Killed, Recorder, make_runner

UNIT = "add-marker/1"


class Tick:
    def __init__(self, inst: Installation, recorder: Recorder) -> None:
        self.inst, self.recorder, self.store = inst, recorder, recorder.store

    def run(self) -> int:
        return cli.cmd_tick(argparse.Namespace(dry_run=False, only=None), self.inst)

    def next(self) -> tuple[Node, ...]:
        async def look() -> tuple[Node, ...]:
            async with open_checkpointer(unit_graphs_path(self.inst.state_dir)) as saver:
                return (await thread_position(saver, UNIT)).next

        return asyncio.run(look())


@pytest.fixture
def tick(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Tick:
    inst = make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        limits={"max_concurrent_stacks": 1},
    )
    recorder = fresh(tmp_path)

    def runner(u: Any, **kwargs: Any) -> Any:
        return make_runner(recorder.store, recorder, tmp_path)

    monkeypatch.setattr(cli, "build_runner", runner)
    monkeypatch.setattr(cli, "fetch_all", lambda inst: None)
    monkeypatch.setattr(cli, "poll_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "plan_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "has_identity", lambda inst, repo: True)
    monkeypatch.setattr(cli, "verify_ready", lambda inst, units, **kwargs: lambda change: True)
    monkeypatch.setattr(cli, "archive_ready_changes", lambda *a, **k: [])
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    monkeypatch.setattr(cli, "may_start_unit", lambda r: Decision(may_start=True, reason="plenty"))
    monkeypatch.setattr(
        cli, "build_fetch_review", lambda: lambda repo, pr: Review(lines=["rename the marker"])
    )
    monkeypatch.setattr(cli, "build_restack", lambda **kw: lambda **a: None)
    monkeypatch.setattr(cli, "build_retarget", lambda: lambda unit, base: None)
    return Tick(inst, recorder)


def test_a_tick__builds_a_unit_on_its_thread(tick: Tick) -> None:
    assert tick.run() == 0

    assert tick.store.get(UNIT).state == IN_REVIEW
    assert tick.recorder.pr_opens == 1
    assert tick.next() == (Node.AWAIT_REVIEW,)


def test_a_unit_killed_mid_node_is_resumed_there_(tick: Tick) -> None:
    tick.recorder.kill_after = "commit:feat"
    with pytest.raises(Killed):
        tick.run()
    assert tick.next() == (Node.IMPLEMENT,)

    assert tick.run() == 0

    assert tick.store.get(UNIT).state == IN_REVIEW
    assert tick.recorder.events.count("claude:impl") == 1
    states = [entry.get("state") for entry in tick.store.get(UNIT).history]
    assert states == [PLANNED, RUNNING, IN_REVIEW], "never put back to planned"


def test_a_second_tick_does_not_build_again(tick: Tick) -> None:
    tick.run()
    built = list(tick.recorder.events)

    assert tick.run() == 0

    assert tick.recorder.events == built
    assert tick.next() == (Node.AWAIT_REVIEW,)
