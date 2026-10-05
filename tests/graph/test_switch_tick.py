"""With no engine setting at all the graph is the engine: the first tick on the
new version converts the units in flight, then runs every unit on its thread
(docs/unit-graph.md, Moving the units in flight)."""

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
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, RUNNING, branch_name
from agent_build_kit.pipeline.usage_guard import Decision
from tests.conftest import make_installation
from tests.factories import unit
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
    # No `engine` setting anywhere: whatever the default is runs the unit.
    monkeypatch.delenv("ABK_ENGINE", raising=False)
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
    monkeypatch.setattr(cli, "build_fetch_review", lambda: lambda repo, pr: ["rename the marker"])
    monkeypatch.setattr(cli, "build_restack", lambda **kw: lambda **a: None)
    monkeypatch.setattr(cli, "build_retarget", lambda: lambda unit, base: None)
    return Tick(inst, recorder)


def test_a_tick_with_no_engine_setting_builds_a_unit_on_its_thread(tick: Tick) -> None:
    assert tick.run() == 0

    assert tick.store.get(UNIT).state == IN_REVIEW
    assert tick.recorder.pr_opens == 1
    assert tick.next() == (Node.AWAIT_REVIEW,)


def test_a_unit_killed_mid_node_is_resumed_there_with_no_engine_setting(tick: Tick) -> None:
    tick.recorder.kill_after = "commit:feat"
    with pytest.raises(Killed):
        tick.run()
    assert tick.next() == (Node.IMPLEMENT,)

    assert tick.run() == 0

    assert tick.store.get(UNIT).state == IN_REVIEW
    assert tick.recorder.events.count("claude:impl") == 1
    states = [entry.get("state") for entry in tick.store.get(UNIT).history]
    assert states == [PLANNED, RUNNING, IN_REVIEW], "never put back to planned"


def test_the_first_tick_converts_a_unit_in_flight_and_resumes_it_where_it_stopped(
    tick: Tick,
) -> None:
    tick.store.set_state(UNIT, PLANNED, branch=branch_name(unit()), resume_from="review")
    tick.recorder.made = 2

    assert tick.run() == 0

    assert tick.recorder.events.count("review") == 1
    assert "claude:impl" not in tick.recorder.events
    assert "claude:tests" not in tick.recorder.events
    assert tick.store.get(UNIT).state == IN_REVIEW
    assert tick.next() == (Node.AWAIT_REVIEW,)


def test_the_first_tick_converts_a_unit_in_review_without_building_it_again(tick: Tick) -> None:
    tick.store.set_state(UNIT, IN_REVIEW, pr=7, branch=branch_name(unit()))

    assert tick.run() == 0

    assert tick.next() == (Node.AWAIT_REVIEW,)
    assert tick.recorder.events == [], "nothing was run for a unit waiting in review"
    assert tick.store.get(UNIT).state == IN_REVIEW


def test_a_second_tick_does_not_convert_again(tick: Tick) -> None:
    tick.run()
    built = list(tick.recorder.events)

    assert tick.run() == 0

    assert tick.recorder.events == built
    assert tick.next() == (Node.AWAIT_REVIEW,)
