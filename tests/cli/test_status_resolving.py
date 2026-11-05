"""`abk status` shows the resolution lane's work: `resolving: N running, M waiting`, each unit as
resolving its base, a run that waits for a usage pause named with the pause.

The lane is a real one over blocking runs (`tests/restack_lane_fakes.py`); what status reads is
what the lane leaves in the state directory, since `abk status` is not the tick's process."""

from __future__ import annotations

import argparse
from functools import partial
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.pause import PAUSE_MARKER, pause_until
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import PLANNED
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.restack_lane_fakes import WAIT, Restacks, repo_behind, units


def printed(capsys: pytest.CaptureFixture[str]) -> list[str]:
    """What was printed, each line without the time the log puts before it."""
    return [line.split("] ", 1)[-1] for line in capsys.readouterr().out.splitlines()]


def test_two_running_and_three_waiting_runs_read_as_a_line_and_as_each_unit_resolving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = make_installation(
        tmp_path,
        planning={
            "state_dir": ".",
            "worktree_root": str(tmp_path.with_name(tmp_path.name + "-trees")),
        },
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit(f"change-{n}/1", change=f"change-{n}") for n in range(1, 6)])
    moves = Restacks()
    monkeypatch.setattr(cli, "current_usage", lambda: None)

    with cli.build_restack_lane(inst, store) as lane:
        for unit in store.all():
            lane.hand_over(unit, partial(moves, unit))
        assert moves.begun["change-2/1"].wait(WAIT)
        capsys.readouterr()
        assert cli.cmd_status(argparse.Namespace(), inst) == 0
        lines = printed(capsys)
        moves.release_all()

    assert "resolving: 2 running, 3 waiting" in lines
    assert not any(line.startswith("restacks:") for line in lines)
    for unit in store.all():
        assert any(unit.id in line and "resolving base main" in line for line in lines), unit.id
    assert not any("restacking onto" in line for line in lines)


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
    assert any("feature/3" in line and "usage pause" in line for line in lines)
