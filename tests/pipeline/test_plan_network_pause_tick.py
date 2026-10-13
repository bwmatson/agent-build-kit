"""A tick under a `network` pause plans nothing, and plans a change waiting for the network
the tick the pause clears, whatever the time of its next try (spec: unit-scheduling).

The planner is the runtime stand-in; the control group is the connect replaced below the
check, as the pause tests do.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit import runtimes
from agent_build_kit.cli import pipeline as cli
from tests.cli.replan_driver import answer, planned, record_plan
from tests.pipeline import test_cli_pipeline as base
from tests.pipeline.test_cli_pipeline import (  # noqa: F401 — fixtures
    TASKS,
    healthy,
    isolated,
    real_plan_all,
    write_change,
)
from tests.pipeline.test_network_pause_tick import Control, tick, write_marker
from tests.runtimes.stand_in import StandInRuntime

pytestmark = pytest.mark.usefixtures("scripted_engine")

CHANGE = "add-marker"


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch) -> Control:
    return Control(monkeypatch)


@pytest.fixture
def planner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> StandInRuntime:
    """The model, answering with a plan for the one change; planning is the real one."""
    runtime = StandInRuntime(answer=answer(planned("add-marker/1", (1,))))
    monkeypatch.setattr(runtimes, "active", lambda: runtime)
    monkeypatch.setattr(cli, "plan_all", real_plan_all)
    write_change(tmp_path, CHANGE, TASKS)
    return runtime


def waiting_record() -> None:
    """One failed attempt, then a wait for the network whose next try is an hour away."""
    now = datetime.now(UTC)
    record_plan(
        base.inst,
        CHANGE,
        ok=False,
        attempts=1,
        waiting="network",
        waits=2,
        since=(now - timedelta(minutes=3)).isoformat(),
        until=(now + timedelta(hours=1)).isoformat(),
        reason="API Error: Can't reach the API server",
    )


def stored_record(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "planned.json").read_text())[CHANGE]


def test_a_tick_that_finds_a_control_host_plans_a_change_waiting_though_its_time_is_ahead(
    healthy,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    probe: Control,
    planner: StandInRuntime,
) -> None:
    waiting_record()
    write_marker(tmp_path, until=datetime.now(UTC) + timedelta(hours=1))

    before = stored_record(tmp_path)

    assert tick(monkeypatch) == []
    assert planner.requests == []
    assert stored_record(tmp_path) == before
    assert (tmp_path / "paused.json").exists()

    probe.up = True
    tick(monkeypatch)

    assert not (tmp_path / "paused.json").exists()
    assert len(planner.requests) == 1
    record = stored_record(tmp_path)
    assert record["ok"] is True
    assert record["attempts"] == 1
    assert "waiting" not in record
    assert "until" not in record


def test_a_wait_for_the_service_is_not_planned_before_its_time_when_the_network_is_up(
    healthy,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    probe: Control,
    planner: StandInRuntime,
) -> None:
    probe.up = True
    now = datetime.now(UTC)
    record_plan(
        base.inst,
        CHANGE,
        ok=False,
        attempts=0,
        waiting="service",
        waits=1,
        since=now.isoformat(),
        until=(now + timedelta(hours=1)).isoformat(),
        reason="API Error: 529",
    )

    tick(monkeypatch)

    assert planner.requests == []
    assert stored_record(tmp_path)["waiting"] == "service"
