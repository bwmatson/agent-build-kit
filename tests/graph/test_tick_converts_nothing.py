"""A tick moves no unit onto a thread: there is no old engine left to convert from."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.events import Review
from agent_build_kit.pipeline.units import IN_REVIEW, branch_name
from agent_build_kit.pipeline.usage_guard import Decision
from tests.conftest import make_installation
from tests.factories import unit
from tests.graph_driver import fresh
from tests.runner_fakes import make_runner

UNIT = "add-marker/1"


def test_a_tick_logs_no_move_onto_a_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
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
        cli, "build_fetch_review", lambda **_: lambda repo, pr: Review(lines=["rename the marker"])
    )
    monkeypatch.setattr(cli, "build_restack", lambda **kw: lambda **a: None)
    monkeypatch.setattr(cli, "build_retarget", lambda: lambda unit, base: None)
    # A unit in review with no thread is what the conversion used to seed one for.
    recorder.store.set_state(UNIT, IN_REVIEW, pr=7, branch=branch_name(unit()))
    capsys.readouterr()

    assert cli.cmd_tick(argparse.Namespace(dry_run=False, only=None), inst) == 0

    output = capsys.readouterr()
    assert "moved onto a thread" not in output.out + output.err
