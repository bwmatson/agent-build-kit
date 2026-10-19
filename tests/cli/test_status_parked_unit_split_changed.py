"""`abk status` shows a parked unit whose group's `Split:` changed: waiting for the new split
while it is held, and requeued with the reason once reworked (spec:
a-parked-unit-follows-its-groups-split)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import PLANNED
from tests.parked_split_support import hold, installation, park, store_of
from tests.split_changed_support import Reworks, release, write_split

pytestmark = pytest.mark.usefixtures("scripted_engine")


def status(inst, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> list[str]:
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    capsys.readouterr()
    assert cli.cmd_status(argparse.Namespace(), inst) == 0
    return capsys.readouterr().out.splitlines()


def test_a_deferred_unit_says_the_new_split_the_hold_and_that_it_reworks_when_released(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path, acp=None, claude_code=None, gpu=None)
    store = store_of(inst)
    park(store, "moved/1", ("acp",), split="acp")
    park(store, "same/1", ("acp",), split="acp")
    write_split(inst, "gpu", change="moved")
    write_split(inst, "acp", change="same")
    hold(inst, "gpu")

    lines = status(inst, monkeypatch, capsys)

    [moved] = [line for line in lines if "moved/1" in line and "e2e-test split" in line]
    assert "gpu" in moved and "the usage window is spent" in moved
    assert "reworks when it is released" in moved
    assert "resumes this round" not in moved
    [same] = [line for line in lines if "same/1" in line and "e2e-test split" in line]
    assert "resumes this round" in same, "its existing line"
    assert "reworks" not in same


def test_a_reworked_unit_is_requeued_and_its_history_names_both_splits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path, acp=True, claude_code=False)
    store = store_of(inst)
    park(store, splits=("acp",), split="acp")
    Reworks(monkeypatch, store, thread=False)
    write_split(inst, "claude_code")

    release(inst, store)
    lines = status(inst, monkeypatch, capsys)

    unit = store.get("feature/1")
    assert unit.state == PLANNED
    assert "acp" in unit.note and "claude_code" in unit.note
    [shown] = [line for line in lines if "feature/1" in line and "requeued" in line]
    assert "claude_code" in shown
    assert not any("e2e-test split" in line for line in lines), "no longer parked"
