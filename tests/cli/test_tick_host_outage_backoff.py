"""A pass readmits a unit parked for the code host being unavailable only once its
backoff has elapsed: 1, 2, 5, 10 and 30 minutes by consecutive parking, measured on
`spans.clock` from when it was parked. Until then it is skipped, and the log says
how long remains."""

from __future__ import annotations

import argparse

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import FAILED, PLANNED
from tests.cli.test_tick_scheduling import (  # noqa: F401
    builder,
    isolated,
    stored,
    tick,
    workspace,
)
from tests.fake_clock import FakeClock, install

pytestmark = pytest.mark.usefixtures("scripted_engine")

UNIT = "feature/1"
MINUTE = 60
BACKOFF_MINUTES = [1, 2, 5, 10, 30, 30, 30]


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    return install(monkeypatch)


def park(store: UnitStore, *, attempts: int) -> None:
    """The unit as a build leaves it after being parked `attempts` times in a row, now."""
    store.upsert([stored(UNIT)])
    for _ in range(attempts):
        store.record_step(UNIT, "open_pr")
        store.set_state(
            UNIT,
            PLANNED,
            note="create_pr: host unavailable after 3 attempts",
            cause=Cause.HOST_UNAVAILABLE,
        )


def test_status_lists_a_failed_unit_and_a_unit_waiting_for_the_host(
    tmp_path,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst = workspace(tmp_path)
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored("broke/1"), stored("waits/1")])
    store.record_step("broke/1", "push")
    store.set_state("broke/1", FAILED, note="OSError: disk full", cause=Cause.FAILED)
    store.record_step("waits/1", "open_pr")
    store.set_state(
        "waits/1", PLANNED, note="create_pr: host unavailable", cause=Cause.HOST_UNAVAILABLE
    )

    assert cli.cmd_status(argparse.Namespace(), inst) == 0

    lines = capsys.readouterr().out.splitlines()
    failed = next(line for line in lines if "broke/1" in line and "failed" in line)
    assert "at push" in failed and "OSError: disk full" in failed
    waiting = next(line for line in lines if "waits/1" in line and "code host" in line)
    assert "at open_pr" in waiting and "60s remain" in waiting
    assert "create_pr: host unavailable" in waiting
