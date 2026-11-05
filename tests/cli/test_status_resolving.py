"""`abk status` names a run that waits for a usage pause under the `resolving:` line, with the
pause as its reason. The lane's own lines are held by `test_status_restacks.py`."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.pause import PAUSE_MARKER, pause_until
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import PLANNED
from tests.restack_lane_fakes import printed, repo_behind, units


def test_a_run_waiting_for_a_usage_pause_is_listed_with_the_pause_as_its_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = repo_behind(tmp_path, monkeypatch)
    store = UnitStore(tmp_path / "units.json")
    store.upsert(units(3)[2:])
    store.set_state("feature/3", PLANNED, branch="spec/feature/3", cause=Cause.RESTACK_DEFERRED)
    pause_until(None, reason="session at 99%", marker=inst.state_dir / PAUSE_MARKER)
    monkeypatch.setattr(cli, "current_usage", lambda: None)

    assert cli.cmd_status(argparse.Namespace(), inst) == 0

    lines = printed(capsys)
    assert "resolving: 0 running, 1 waiting" in lines
    assert any("resolving waiting: feature/3" in line and "usage pause" in line for line in lines)
