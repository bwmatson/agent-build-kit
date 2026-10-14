"""Whether a pass lets a held unit back in does not depend on the clock.

A unit this pass built is let back in once it has been put back after the pass started
it. That order must come from the order of writes, not from timestamps: a clock that
steps back while a build runs (a host re-syncing under load) stamps the put-back before
the start, and a clock that does not move stamps both alike. These tests drive both with
a clock a build moves itself, so nothing waits on a host to misbehave."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED
from tests.fake_clock import FakeClock, install
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

HOUR = 3600


@pytest.fixture(autouse=True)
def warmed(tmp_path: Path) -> None:
    warm_unit_graphs(tmp_path)


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate(monkeypatch)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    return install(monkeypatch)


@pytest.fixture
def builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Builder:
    return install_builder(tmp_path, monkeypatch)


def test_a_unit_that_held_itself_is_started_again_though_the_clock_stepped_back_during_its_build(
    builder: Builder, clock: FakeClock, tmp_path: Path
) -> None:
    inst = workspace(tmp_path, max_concurrent=2)
    builder.store.upsert([stored("moved/1")])
    runs: list[int] = []

    def holds_once() -> str | None:
        runs.append(1)
        if len(runs) > 1:
            return None
        clock.advance(-HOUR)  # after the pass stamped the start, before the build records
        return "held"

    builder.scripts["moved/1"] = holds_once
    builder.ends["moved/1"] = (PLANNED, Cause.BASE_CHANGED, MOVED_NOTE)

    assert tick(inst) == 0

    assert builder.started.count("moved/1") == 2
    assert builder.store.get("moved/1").state == IN_REVIEW


def test_a_unit_that_keeps_holding_itself_is_started_the_bound_with_the_clock_stepping_back(
    builder: Builder, clock: FakeClock, tmp_path: Path
) -> None:
    inst = workspace(tmp_path, max_concurrent=2)
    builder.store.upsert([stored("moved/1")])

    def holds() -> str | None:
        clock.advance(-HOUR)
        return "held"

    builder.scripts["moved/1"] = holds
    builder.ends["moved/1"] = (PLANNED, Cause.BASE_CHANGED, MOVED_NOTE)

    assert tick(inst) == 0

    assert builder.started.count("moved/1") == 1 + cli.REBUILDS_PER_PASS


def test_a_unit_that_held_itself_is_started_again_though_the_clock_never_moved(
    builder: Builder, clock: FakeClock, tmp_path: Path
) -> None:
    """Every stamp is equal: the start and the put-back cannot be told apart by time."""
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
