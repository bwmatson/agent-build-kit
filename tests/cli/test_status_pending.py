"""`abk status` says what the pipeline still owes a pull request, and why."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.graph.state import UnitRun
from agent_build_kit.graph.unit import Position
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import ClosePending, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, SATISFIED
from tests.conftest import make_installation
from tests.factories import stored_unit

ANSWER = json.dumps(
    {
        "replies": [{"comment_id": 11, "body": "done"}, {"comment_id": 12, "body": "moved"}],
        "summary": "Also dropped a key.",
    }
)


def position_of(inst: Installation, unit_id: str) -> Position:
    if unit_id != "one/1":
        return Position()
    return Position(state=UnitRun(unit_id=unit_id, change="one", pending_replies=(ANSWER,)))


def test_status_lists_a_unit_with_unposted_replies_and_a_pending_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = make_installation(
        tmp_path, planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees"))
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("one/1", change="one"), stored_unit("two/1", change="two")])
    store.set_state("one/1", IN_REVIEW, pr=5, branch="spec/one/1")
    store.set_state("two/1", SATISFIED, pr=6)
    store.set_close_pending("two/1", ClosePending(pr=6, reason="Elsewhere."))
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    monkeypatch.setattr(cli, "thread_of", position_of)

    assert cli.cmd_status(argparse.Namespace(), workspace) == 0

    lines = capsys.readouterr().out.splitlines()
    replies = next(line for line in lines if "one/1" in line and "unposted" in line)
    assert "#5" in replies
    assert "3 waiting" in replies, "two replies and a summary, not one answer"
    close = next(line for line in lines if "two/1" in line and "close" in line)
    assert "#6" in close
