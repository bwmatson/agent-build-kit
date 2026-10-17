"""A carried entry on a unit the pass started readmits nothing and logs its skip once."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import PLANNED
from tests.tick_driver import count_refreshes
from tests.tick_pass import (
    Builder,
    install_builder,
    isolate,
    stored,
    tick,
    warm_unit_graphs,
    workspace,
)
from tests.waiting import wait_for

SEVERAL_REFRESHES = 5
WAIT = 30
SKIP = "held/1: not started again in this pass, stopped for split_held"

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture(autouse=True)
def warmed(tmp_path: Path) -> None:
    warm_unit_graphs(tmp_path)


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate(monkeypatch)
    monkeypatch.setattr(cli, "REFRESH_SECONDS", 0.05)


@pytest.fixture
def builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Builder:
    return install_builder(tmp_path, monkeypatch)


def replan(store: UnitStore, change: str) -> None:
    """A replan that omits the change's unit, then one that includes it again."""
    units = [unit for unit in store.all() if unit.change != change]
    store.upsert(units, change=change)
    store.upsert(store.all(), change=change)


def test_a_carried_entry_on_a_started_unit_is_not_readmitted_and_its_skip_is_logged_once(
    builder: Builder,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst = workspace(tmp_path, max_concurrent=2)
    builder.store.upsert([stored("held/1"), stored("slow/1", repo="platform")])
    builder.ends["held/1"] = (PLANNED, Cause.SPLIT_HELD, "the split is held")
    builder.scripts["held/1"] = lambda: "held"
    refreshes = count_refreshes(monkeypatch)

    def slow() -> None:
        wait_for(lambda: "held/1" in builder.finished, what="held/1 to finish", timeout=WAIT)
        refreshes.wait_for(refreshes.count + 2, timeout=WAIT)
        replan(builder.store, "held")
        refreshes.wait_for(refreshes.count + SEVERAL_REFRESHES, timeout=WAIT)

    builder.scripts["slow/1"] = slow

    assert tick(inst) == 0

    assert builder.started.count("held/1") == 1
    assert builder.store.get("held/1").cause is Cause.SPLIT_HELD
    out = capsys.readouterr()
    assert (out.out + out.err).count(SKIP) == 1


def test_a_carried_base_changed_entry_on_an_unstarted_unit_changes_nothing(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = workspace(tmp_path, max_concurrent=2)
    builder.store.upsert([stored("idle/1"), stored("slow/1", repo="platform")])
    builder.store.set_state("idle/1", PLANNED, note="base moved", cause=Cause.BASE_CHANGED)
    refreshes = count_refreshes(monkeypatch)

    def slow() -> None:
        replan(builder.store, "idle")
        refreshes.wait_for(refreshes.count + SEVERAL_REFRESHES, timeout=WAIT)

    builder.scripts["slow/1"] = slow

    assert tick(inst, only=["slow/1"]) == 0

    assert builder.started == ["slow/1"]
    idle = builder.store.get("idle/1")
    assert (idle.state, idle.cause) == (PLANNED, Cause.BASE_CHANGED)


def test_a_unit_sent_back_for_rework_is_readmitted_beside_a_carried_one(
    builder: Builder, tmp_path: Path
) -> None:
    inst = workspace(tmp_path, max_concurrent=2)
    builder.store.upsert(
        [stored("sent/1"), stored("held/1", repo="platform"), stored("slow/1", repo="platform")]
    )
    builder.ends["sent/1"] = (PLANNED, Cause.REWORK, "reworking")
    builder.ends["held/1"] = (PLANNED, Cause.SPLIT_HELD, "the split is held")
    runs: list[int] = []

    def once() -> str | None:
        runs.append(1)
        return "held" if len(runs) == 1 else None

    builder.scripts["sent/1"] = once
    builder.scripts["held/1"] = lambda: "held"

    def slow() -> None:
        wait_for(lambda: "held/1" in builder.finished, what="held/1 to finish", timeout=WAIT)
        replan(builder.store, "held")
        wait_for(
            lambda: builder.started.count("sent/1") == 2,
            what="sent/1 to be started a second time",
            timeout=WAIT,
        )

    builder.scripts["slow/1"] = slow

    assert tick(inst) == 0

    assert builder.started.count("sent/1") == 2
    assert builder.started.count("held/1") == 1
    assert builder.store.get("held/1").cause is Cause.SPLIT_HELD
