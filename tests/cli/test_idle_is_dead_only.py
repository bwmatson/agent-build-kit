"""Idle means a run that ended without an outcome (spec: usage-pause-slots): a running unit with
no lock, no thread and no recorded pause is reclaimed as before, a pause whose thread is gone is
cleared and its unit reclaimed too, and a unit paused with its thread is left."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import PLANNED, RUNNING
from tests import fake_clock
from tests.cli.usage_pause_support import (
    isolate_round,
    pause_for_usage,
    unit,
    with_threads,
    workspace,
)

KILLED = "killed/1"
GONE = "gone/1"
WAITING = "waiting/1"


def test_only_a_run_that_ended_without_an_outcome_is_reclaimed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = fake_clock.install(monkeypatch)
    isolate_round(tmp_path, monkeypatch)
    inst, store = workspace(tmp_path, [unit(KILLED), unit(GONE), unit(WAITING)])
    until = clock.now() + timedelta(hours=3)
    store.set_state(KILLED, RUNNING, branch=f"spec/{KILLED}")
    pause_for_usage(store, GONE, until)
    pause_for_usage(store, WAITING, until)
    with_threads(monkeypatch, WAITING)

    cli.reclaim_stranded(inst, store)

    assert store.get(KILLED).state == PLANNED
    assert store.get(GONE).state == PLANNED
    assert store.get(GONE).paused_until is None
    assert store.get(WAITING).state == RUNNING
    assert store.get(WAITING).paused_until == until
