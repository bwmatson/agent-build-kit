"""Whether a pass lets a held unit back in does not depend on the wall clock.

A unit this pass built is let back in once the record of it being put back is later than
the start of its build. That order was read off two timestamps; a clock that steps back
while a build runs (a host re-syncing under load) puts the record before the start and
the unit is left out for the rest of the pass, however long a slow build keeps it going.
These tests step the clock back deterministically instead of waiting for a host to."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED
from tests.tick_pass import (
    MOVED_NOTE,
    Builder,
    install_builder,
    isolate,
    stored,
    tick,
    warm_unit_graphs,
    workspace,
)

pytestmark = pytest.mark.usefixtures("scripted_engine")


class SteppedBackClock:
    """The system clock after a step back: every stamp it makes is an hour behind."""

    def __init__(self, real: spans.Clock) -> None:
        self._real = real

    def now(self) -> datetime:
        return self._real.now() - timedelta(hours=1)

    def monotonic(self) -> float:
        return self._real.monotonic()


@pytest.fixture(autouse=True)
def warmed(tmp_path: Path) -> None:
    warm_unit_graphs(tmp_path)


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate(monkeypatch)
    monkeypatch.setattr(spans, "clock", SteppedBackClock(spans.clock))


@pytest.fixture
def builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Builder:
    return install_builder(tmp_path, monkeypatch)


def test_a_unit_that_held_itself_is_started_again_though_the_clock_stepped_back(
    builder: Builder, tmp_path: Path
) -> None:
    inst = workspace(tmp_path, max_concurrent=2)
    builder.store.upsert([stored("moved/1")])
    runs: list[int] = []

    def holds_once() -> str | None:
        runs.append(1)
        return "held" if len(runs) == 1 else None

    builder.scripts["moved/1"] = holds_once
    builder.ends["moved/1"] = (PLANNED, Cause.BASE_CHANGED, MOVED_NOTE)

    assert tick(inst) == 0

    assert builder.started.count("moved/1") == 2
    assert builder.store.get("moved/1").state == IN_REVIEW


def test_a_unit_that_keeps_holding_itself_is_started_the_bound_though_the_clock_stepped_back(
    builder: Builder, tmp_path: Path
) -> None:
    inst = workspace(tmp_path, max_concurrent=2)
    builder.store.upsert([stored("moved/1")])
    builder.scripts["moved/1"] = lambda: "held"
    builder.ends["moved/1"] = (PLANNED, Cause.BASE_CHANGED, MOVED_NOTE)

    assert tick(inst) == 0

    assert builder.started.count("moved/1") == 1 + cli.REBUILDS_PER_PASS
