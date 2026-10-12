"""A tick over one unit's thread with its edges faked: what `graph` in the tick tests is.

`Setup` drives `abk tick` and the poller's events through the entry points a person or the
timer calls, over the recorder's fake runner, and looks at where a unit's thread waits."""

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
from agent_build_kit.pipeline.usage_guard import Decision
from tests.conftest import make_installation
from tests.graph_driver import fresh
from tests.runner_fakes import Recorder, make_runner

UNIT = "add-marker/1"
OTHER = "add-marker/2"
real_poll_all = cli.poll_all


class Setup:
    def __init__(
        self,
        inst: Installation,
        recorder: Recorder,
        options: dict[str, Any],
        patch: pytest.MonkeyPatch,
    ) -> None:
        self.inst, self.recorder, self.options, self.patch = inst, recorder, options, patch
        self.store = recorder.store

    def tick(self) -> int:
        return cli.cmd_tick(argparse.Namespace(dry_run=False, only=None), self.inst)

    def next(self, unit_id: str = UNIT) -> tuple[Node, ...]:
        async def look() -> tuple[Node, ...]:
            async with open_checkpointer(unit_graphs_path(self.inst.state_dir)) as saver:
                return (await thread_position(saver, unit_id)).next

        return asyncio.run(look())

    def poll(self, *events: tuple[str, dict[str, Any]], pr: int = 7) -> list[bool]:
        """Report `events` for pull request `pr` as the poller does, and return
        what the dispatch answered each."""
        answers: list[bool] = []

        class Reports:
            def __init__(self, *, repo: str, dispatch: Any, **kwargs: Any) -> None:
                self.repo, self.dispatch = repo, dispatch

            def poll(self) -> None:
                if self.repo != "example/app":
                    return
                for name, kwargs in events:
                    answers.append(self.dispatch(name, pr, pull=None, **kwargs))

        self.patch.setattr(cli, "Poller", Reports)
        real_poll_all(self.inst, store=self.store)
        return answers


def make_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Setup:
    inst = make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        limits={"max_concurrent_stacks": 1},
    )
    recorder = fresh(tmp_path)
    options: dict[str, Any] = {}

    def runner(u: Any, **kwargs: Any) -> Any:
        return make_runner(recorder.store, recorder, tmp_path, **options)

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
        cli, "build_fetch_review", lambda **_: lambda repo, pr: Review(lines=["rename the marker"])
    )
    monkeypatch.setattr(cli, "build_restack", lambda **kw: lambda **a: None)
    monkeypatch.setattr(cli, "build_retarget", lambda: lambda unit, base: None)
    return Setup(inst, recorder, options, monkeypatch)
