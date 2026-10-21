"""`abk status` after a unit parked on a split is requeued for rework (spec:
a-unit-parked-on-a-split-can-be-requeued): it no longer waits for the split, it is a requeued
planned unit in the ready queue whose history carries the note, and a unit still parked keeps
its line."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import PLANNED
from tests.parked_split_support import hold, installation, park, store_of
from tests.split_changed_support import UNIT, Reworks

NOTE = "retag the test; it uses a scripted agent"
WAITING = "waiting for e2e-test split acp"
OTHER = "other/1"
QUEUE = "ready queue (start order):"


def status(
    inst: Installation, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> list[str]:
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    capsys.readouterr()
    assert cli.cmd_status(argparse.Namespace(), inst) == 0
    return capsys.readouterr().out.splitlines()


def test_a_rework_requeue_ends_the_waiting_line_and_queues_the_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path, acp=None, claude_code=None, gpu=None)
    store = store_of(inst)
    park(store, splits=("acp",), split="acp")
    park(store, OTHER, splits=("acp",), split="acp")
    hold(inst, "acp")
    Reworks(monkeypatch, store, thread=False)
    before = status(inst, monkeypatch, capsys)
    assert any(WAITING in line and f"{UNIT} " in line for line in before)

    assert cli.requeue(inst, UNIT, "rework", say=lambda *a, **k: None, note=NOTE) == 0

    lines = status(inst, monkeypatch, capsys)
    waiting = [line for line in lines if WAITING in line]
    assert len(waiting) == 1 and OTHER in waiting[0], "only the other unit still waits"
    after = store.get(UNIT)
    assert (after.state, after.cause) == (PLANNED, Cause.REQUEUED)
    at = next(n for n, line in enumerate(lines) if QUEUE in line)
    queue = lines[at + 1 :]
    assert any(f"{UNIT} " in line for line in queue), "the requeued unit is in the ready queue"
    entry = after.history[-1]["note"]
    assert "acp" in entry and NOTE in entry
