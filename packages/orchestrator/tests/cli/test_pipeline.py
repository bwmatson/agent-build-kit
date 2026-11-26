"""`abk status` names each outline ready to detail on a line of its own."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit import run_support
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.units import UnitState
from tests.conftest import make_installation
from tests.factories import BIG_PLAN_REASON, stored_unit, write_given_up_plans, write_outline


def outline_lines(inst: Installation, capsys: pytest.CaptureFixture[str]) -> list[str]:
    capsys.readouterr()
    assert cli.cmd_status(argparse.Namespace(), inst) == 0
    return [line for line in capsys.readouterr().out.splitlines() if "outline" in line]


def test_status_prints_one_line_for_the_ready_outline_and_none_for_the_far_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("agent_build_kit.run_support.current_usage", lambda: None)
    inst = make_installation(tmp_path, planning=dict(state_dir="."))
    (inst.changes_dir / "base").mkdir(parents=True)
    (inst.changes_dir / "base" / "tasks.md").write_text("## 1. [app] [unit-test] Work\n")
    store = run_support.store_for(inst)
    store.upsert([stored_unit("base/1", change="base", groups=(1,))])
    store.set_state("base/1", UnitState.RUNNING)
    assert outline_lines(inst, capsys) == []
    write_outline(inst, "next", "Waits on: base group 1 — needs it")
    write_outline(inst, "far", "Waits on: base group 3 — needs it")

    lines = outline_lines(inst, capsys)

    assert len([line for line in lines if "next" in line]) == 1
    assert not [line for line in lines if "far" in line]


def test_status_prints_a_planning_line_only_for_the_active_change_whose_planning_gave_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("agent_build_kit.run_support.current_usage", lambda: None)
    inst = make_installation(tmp_path, planning=dict(state_dir="."))
    write_given_up_plans(inst)

    capsys.readouterr()
    assert cli.cmd_status(argparse.Namespace(), inst) == 0
    lines = [
        line
        for line in capsys.readouterr().out.splitlines()
        if "planning " in line and "guard planning" not in line
    ]

    assert len(lines) == 1
    assert "big" in lines[0]
    assert "given up" in lines[0]
    assert BIG_PLAN_REASON in lines[0]
    for other in ("edited", "gone", "old"):
        assert not [line for line in lines if other in line]
