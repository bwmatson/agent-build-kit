"""`abk status` and the graph page show the lane's work: `restacks: N running, M waiting`, each
unit as restacking onto its base, a restack that waits for a usage pause named with the pause.

The lane is a real one over blocking restacks (`tests/restack_lane_fakes.py`), read from the
same process; what status reads is what the lane leaves in the state directory, since `abk
status` is not the process that runs the tick. A lane whose process has gone is made by handing
work over under the pid of a process that has ended.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from functools import partial
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.resolution_lane import Lane
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.restack_lane_fakes import WAIT, Restacks


class Scene:
    """Five units of five changes, each to be restacked onto `main` by a lane of two."""

    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.inst = make_installation(
            root,
            planning={"state_dir": ".", "worktree_root": str(root.with_name(root.name + "-trees"))},
        )
        self.store = UnitStore(root / "units.json")
        self.store.upsert([stored_unit(f"change-{n}/1", change=f"change-{n}") for n in range(1, 6)])
        self.moves = Restacks()
        monkeypatch.setattr(cli, "current_usage", lambda: None)

    def lane(self) -> Lane:
        return cli.build_restack_lane(self.inst, self.store)

    def hand_over(self, lane: Lane) -> None:
        """Every unit to the lane: the first two start and the rest wait."""
        for unit in self.store.all():
            lane.hand_over(unit, partial(self.moves, unit))
        assert self.moves.begun["change-2/1"].wait(WAIT)

    def status(self, capsys: pytest.CaptureFixture[str]) -> list[str]:
        capsys.readouterr()
        assert cli.cmd_status(argparse.Namespace(), self.inst) == 0
        return printed(capsys)

    def page(self) -> str:
        assert cli.cmd_graph(argparse.Namespace(), self.inst) == 0
        return self.inst.graph_page.read_text()


def printed(capsys: pytest.CaptureFixture[str]) -> list[str]:
    """What was printed, each line without the time the log puts before it."""
    return [line.split("] ", 1)[-1] for line in capsys.readouterr().out.splitlines()]


def ended_process() -> int:
    """The pid of a process that has run and ended."""
    child = subprocess.Popen([sys.executable, "-I", "-c", ""])
    child.wait()
    return child.pid


def test_two_running_and_three_waiting_restacks_read_as_a_line_and_as_each_unit_restacking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scene = Scene(tmp_path, monkeypatch)
    with scene.lane() as lane:
        scene.hand_over(lane)

        lines = scene.status(capsys)
        page = scene.page()
        scene.moves.release_all()

    assert "resolving: 2 running, 3 waiting" in lines
    for unit in scene.store.all():
        assert any(unit.id in line and "resolving base main" in line for line in lines), unit.id
    assert page.count("resolving base main") == 5
    assert not any(line.startswith("resolving:") for line in scene.status(capsys)), "all drained"
    assert "resolving base" not in scene.page()


def test_a_lane_record_whose_process_has_gone_is_ignored_and_a_live_one_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, list[str]] = {}
    for name, pid in (("live", os.getpid()), ("gone", ended_process())):
        scene = Scene(tmp_path / name, monkeypatch)
        with scene.lane() as lane:
            # Handed over under `pid`, so that is the owner the record names.
            with monkeypatch.context() as owned:
                owned.setattr(os, "getpid", lambda pid=pid: pid)
                scene.hand_over(lane)
            seen[name] = scene.status(capsys)
            scene.moves.release_all()

    assert "resolving: 2 running, 3 waiting" in seen["live"]
    assert not any(line.startswith("resolving:") for line in seen["gone"])
    assert not any("resolving base" in line for line in seen["gone"])
