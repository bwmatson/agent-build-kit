"""A tick whose only work is a unit parked for a held e2e-test split is not idle and runs the
release step, which reads the state file and the configuration alone (spec:
e2e-runtime-parking)."""

from __future__ import annotations

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.config import dump
from agent_build_kit.graph.checkpointer import unit_graphs_path
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.stack_runner import RunOutcome, RunStatus
from agent_build_kit.pipeline.units import MERGED
from tests.parked_split_support import (
    Deliveries,
    hold,
    installation,
    park,
    store_of,
    stub_round,
)

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    made = installation(tmp_path, acp=None)
    (made.root / "abk.yaml").write_text(dump(made.config))
    monkeypatch.chdir(made.root)
    stub_round(monkeypatch)
    monkeypatch.setattr(cli, "verify_ready", lambda inst, units, **kwargs: lambda change: True)
    with closing(sqlite3.connect(unit_graphs_path(tmp_path))) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
    return made


class Builder:
    """Stands in for `build_runner`: a unit released into a build is started, not built."""

    def __init__(self) -> None:
        self.started: list[str] = []

    def __call__(self, unit: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(run=lambda unit, *, base, graph: self._run(unit))

    def _run(self, unit: Any) -> RunOutcome:
        self.started.append(unit.id)
        return RunOutcome(status=RunStatus("open"), detail=f"open {unit.id}", pr=1)


def tick(inst: Installation) -> int:
    return cli.cmd_tick(argparse.Namespace(dry_run=False), inst)


def test_a_tick_whose_only_work_is_a_parked_unit_is_not_idle_and_releases_it(
    inst: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = Deliveries(monkeypatch)
    monkeypatch.setattr(cli, "build_runner", Builder())
    park(store_of(inst))
    assert cli.has_work(inst, store_of(inst))

    assert tick(inst) == 0

    assert thread.delivered == [("feature/1", "requeue")]


def test_a_tick_with_nothing_waiting_is_idle_and_does_not_run_the_release_step(
    inst: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran: list[str] = []
    monkeypatch.setattr(cli, "release_split_held", lambda *args, **kwargs: ran.append("release"))
    hold(inst, "acp")
    store = store_of(inst)
    park(store)
    assert tick(inst) == 0
    assert ran == ["release"], "a unit still waiting is work: the step runs and releases nothing"

    store.set_state("feature/1", MERGED, pr=1)
    ran.clear()

    assert not cli.has_work(inst, store)
    assert tick(inst) == 0
    assert ran == [], "nothing waiting: idle, as before"


def test_the_release_step_reads_the_state_file_and_the_configuration_and_evaluates_no_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = tmp_path / "gate-was-asked"
    gate = {"command": ["sh", "-c", f"touch {asked}"], "on_unknown": "hold"}
    inst = installation(tmp_path, acp=None, gate=gate)
    thread = Deliveries(monkeypatch)
    store = store_of(inst)
    park(store)

    cli.release_split_held(inst, store)

    assert thread.delivered == [("feature/1", "requeue")], "nothing in the file holds it"
    assert not asked.exists(), "the gate's command was not run"
