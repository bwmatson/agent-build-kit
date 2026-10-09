"""A pass readmits a unit parked for the code host being unavailable only once its
backoff has elapsed: 1, 2, 5, 10 and 30 minutes by consecutive parking, measured on
`spans.clock` from when it was parked. Until then it is skipped, and the log says
how long remains."""

from __future__ import annotations

import argparse
import time

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import FAILED, IN_REVIEW, PLANNED
from tests.cli.test_tick_scheduling import (  # noqa: F401
    Builder,
    builder,
    eventually,
    isolated,
    stored,
    tick,
    warm_unit_graphs,
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


@pytest.mark.parametrize("attempts", range(1, len(BACKOFF_MINUTES) + 1))
def test_the_pass_skips_a_parked_unit_until_its_backoff_has_elapsed(
    tmp_path,
    builder: Builder,  # noqa: F811
    clock: FakeClock,
    attempts: int,
    capsys: pytest.CaptureFixture[str],
) -> None:
    wait = BACKOFF_MINUTES[attempts - 1] * MINUTE
    park(builder.store, attempts=attempts)
    inst = workspace(tmp_path)

    clock.advance(wait - 1)
    tick(inst)
    assert builder.started == [], "readmitted a second early"
    waiting = [line for line in capsys.readouterr().out.splitlines() if UNIT in line]
    assert any("remain" in line for line in waiting), "the log does not say how long remains"

    clock.advance(2)
    tick(inst)
    assert builder.started == [UNIT]


def test_a_build_that_succeeds_resets_the_count(
    tmp_path,
    builder: Builder,  # noqa: F811
    clock: FakeClock,
) -> None:
    park(builder.store, attempts=3)
    clock.advance(5 * MINUTE + 1)

    tick(workspace(tmp_path))

    unit = builder.store.get(UNIT)
    assert unit.state == IN_REVIEW
    assert unit.parked_attempts == 0


@pytest.mark.parametrize("backoff_over", [False, True])
def test_the_running_pass_readmits_a_unit_it_parked_only_after_its_backoff(
    tmp_path,
    builder: Builder,  # noqa: F811
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
    backoff_over: bool,
) -> None:
    inst = workspace(tmp_path, max_concurrent=2)
    builder.store.upsert([stored("sent/1"), stored("slow/1", repo="platform")])
    monkeypatch.setattr(cli, "REFRESH_SECONDS", 0.05)
    runs: list[int] = []

    def parks_once() -> str | None:
        runs.append(1)
        return "held" if len(runs) == 1 else None

    builder.scripts["sent/1"] = parks_once
    builder.ends["sent/1"] = (PLANNED, Cause.HOST_UNAVAILABLE, "create_pr: host unavailable")

    def slow() -> str | None:
        assert eventually(lambda: "sent/1" in builder.finished)
        if not backoff_over:
            time.sleep(0.4)  # several refreshes, in which a readmission would show
            return None
        clock.advance(MINUTE + 1)
        return None if eventually(lambda: builder.started.count("sent/1") == 2) else "failed"

    builder.scripts["slow/1"] = slow

    assert tick(inst) == 0

    assert builder.started.count("sent/1") == (2 if backoff_over else 1)


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
