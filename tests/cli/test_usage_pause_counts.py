"""A usage pause at the gate is recorded on the unit, counts toward the units-in-progress limit
and is cleared when the gate allows (spec: usage-pause-slots, a unit paused for usage is recorded
and counts as in progress). The gate is run through the graph; the rounds over a stand-in usage
decision and clock."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline import wiring
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import RUNNING
from agent_build_kit.pipeline.usage_guard import Decision
from tests import fake_clock
from tests.cli.usage_pause_support import (
    isolate_round,
    pause_for_usage,
    started_by,
    unit,
    with_threads,
    workspace,
)
from tests.graph_driver import fresh, tick

UNTIL = datetime(2030, 1, 1, 9, 30, tzinfo=UTC)
WINDOW = "session usage at 88%"
LIMIT = 4


def test_a_refusal_at_the_gate_records_a_usage_pause_on_the_unit(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)

    tick(tmp_path, recorder, may_start=lambda: (False, WINDOW), resume_at=lambda: UNTIL)

    stored = recorder.store.get("add-marker/1")
    assert stored.state == "running"
    assert stored.cause is Cause.USAGE
    assert stored.paused_until == UNTIL


def test_the_pause_is_cleared_when_the_gate_later_allows(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder, may_start=lambda: (False, WINDOW), resume_at=lambda: UNTIL)

    tick(tmp_path, recorder, may_start=lambda: (True, "usage fine"))

    stored = recorder.store.get("add-marker/1")
    assert stored.paused_until is None
    assert stored.cause is not Cause.USAGE


PAUSED_SIZE = 500


def refuse_the_paused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard refuses the paused units' step (the size marks them) and allows anything else,
    so nothing is resumed and the waiting units are held back by the limit alone, not by the
    account. The round's own ask is for the smallest unit that could start, which is a waiting
    one, so it is allowed."""

    def decide(*, estimated_lines: int | None = None, **_: object) -> Decision:
        if estimated_lines == PAUSED_SIZE:
            return Decision(may_start=False, reason="session usage at 93%", resume_at=UNTIL)
        return Decision(may_start=True, reason="plenty")

    monkeypatch.setattr(cli, "decide_start", decide)
    monkeypatch.setattr(wiring, "decide_start", decide)


def paused_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, paused_count: int, live: bool
) -> list[str]:
    """A round with `paused_count` units paused at the gate (and one build in flight when
    `live`), three waiting units, a limit of four and workers to spare."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    clock = fake_clock.install(monkeypatch)
    isolate_round(tmp_path, monkeypatch)
    refuse_the_paused(monkeypatch)
    paused = [f"paused{n}/1" for n in range(paused_count)]
    inst, store = workspace(
        tmp_path,
        [
            *([unit("live/1")] if live else []),
            *[unit(uid, estimated_lines=PAUSED_SIZE) for uid in paused],
            *[unit(f"wait{n}/1") for n in range(3)],
        ],
        limit=LIMIT,
        workers=12,
    )
    if live:
        store.set_state("live/1", RUNNING, branch="spec/live/1")
    for uid in paused:
        pause_for_usage(store, uid, clock.now() + timedelta(hours=3))
    with_threads(monkeypatch, *paused)
    return started_by(inst, store, building=("live/1",) if live else ())


def test_units_paused_at_the_gate_fill_the_limit_and_no_further_unit_is_admitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 2026-10-27 shape: nine units `running`, eight paused at the gate and one with a build
    in flight, against a limit of four. Workers are plentiful and the guard refuses the paused
    units, so nothing resumes and only the limit holds the waiting units back: the paused units
    are in progress, so none is admitted."""
    ready = paused_round(tmp_path, monkeypatch, paused_count=8, live=True)

    assert ready == []


def test_a_paused_unit_holds_its_place_and_a_free_place_admits_a_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three paused units and the live one fill the limit of four; with the live unit gone the
    paused three leave exactly one place, so one waiting unit is admitted and no more."""
    full = paused_round(tmp_path / "full", monkeypatch, paused_count=3, live=True)
    one_free = paused_round(tmp_path / "free", monkeypatch, paused_count=3, live=False)

    assert full == []
    assert one_free == ["wait0/1"]
