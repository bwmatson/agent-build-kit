"""`abk status` prints the usage forecast after the estimate line, from the history, the step rows
and the installed timers, with no call (spec: usage-pause).

The history is the real ledger and verdict file beside the cache; only the endpoint, the home
directory and `systemctl` are faked. Calibration is 2.5 points a dollar, so `auto` units that
cost $2.40 are 6.0 points and `full` units that cost $3.20 are 8.0."""

import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit import runtimes
from agent_build_kit.cli import build_parser
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import RUNNING
from agent_build_kit.pipeline.usage_forecast_record import FORECASTS_NAME, StepRow, record_admission
from agent_build_kit.pipeline.verdict import ReviewTier
from tests.conftest import make_installation
from tests.factories import unit
from tests.runtimes.stand_in import StandInRuntime
from tests.usage_cost_estimate import OBSERVED_AGE
from tests.usage_forecast_fixtures import Fixture
from tests.usage_forecast_gate import EXACT, keep_points, keep_timer, lay, lay_calls
from tests.usage_host import Host, payload, refused

LIMITS = {
    "session": {"usage_pause_pct": 80},
    "weekly": {"usage_pause_pct": 80},
    "usage_climb_floor": 2.0,
    **EXACT,
}
BASE = [("tests", 0, 0.8), ("implement", 0, 0.6), ("review", 1, 1.0)]


def history() -> Fixture:
    """Twenty `auto` units of $2.40, twenty `full` units of $3.20 and five `light` units."""
    found = Fixture()
    found.units(20, ReviewTier.AUTO, BASE)
    found.units(20, ReviewTier.FULL, [*BASE, ("review", 2, 0.8)])
    found.units(5, ReviewTier.LIGHT, BASE)
    return found


def installation(tmp_path: Path, host: Host, **limits: object):
    """An installation whose state directory is the host's, a reading 89 minutes old, a recent
    refusal and a cool-down, so the estimate line is printed, and the calibration kept."""
    inst = make_installation(
        tmp_path / "planning",
        planning={"state_dir": "."},
        runtimes={"claude_code": {"limits": {**LIMITS, **limits}}},
    )
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    host.keep_in(inst.state_dir)
    host.keep_reading(OBSERVED_AGE, payload(session=10.0, weekly=10.0))
    refused(host, cooling=timedelta(minutes=3))
    keep_points(host)
    return inst


def status(inst, capsys: pytest.CaptureFixture[str]) -> list[str]:
    """The lines `abk status` printed."""
    assert cli.cmd_status(build_parser().parse_args(["status"]), inst) == 0
    return capsys.readouterr().out.splitlines()


def forecast_line(lines: list[str]) -> str:
    found = [line for line in lines if "forecast:" in line]
    assert found, "\n".join(lines)
    return found[0]


def step(state: Path, unit_id: str, node: str, round: int) -> None:
    """The guard admitted `unit_id` to its step a moment ago."""
    record_admission(
        state / FORECASTS_NAME,
        StepRow(unit=unit_id, node=node, round=round, at=datetime.now(UTC) - timedelta(seconds=5)),
        None,
        enabled=True,
        say=print,
    )


def run_units(inst, *ids: str) -> None:
    store = cli.store_for(inst)
    store.upsert([unit(each) for each in ids])
    for each in ids:
        store.set_state(each, RUNNING, branch=f"spec/{each}")


def test_the_line_gives_each_tiers_forecast_in_each_window_with_the_units_it_rests_on(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path, host)
    lay(host, history())

    line = forecast_line(status(inst, capsys))

    for tier, figure in [("auto", "6.0%"), ("full", "8.0%")]:
        assert line.count(f"{tier} {figure} (20 units)") == 2, line
    assert line.index("session") < line.index("weekly")
    assert host.asked == 0


def test_a_tier_under_the_minimum_is_marked_as_the_prior(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path, host)
    lay(host, history())

    line = forecast_line(status(inst, capsys))

    # Each window's prior is its own flat allowance.
    assert "session auto 6.0% (20 units), light 17.0% prior" in line
    assert len(re.findall(r"light \d+\.\d% prior", line)) == 2, line
    assert "light 17.0% (" not in line


def test_the_line_shows_the_running_units_remainder_and_the_units_with_no_step_row(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path, host)
    lay(host, history())
    run_units(inst, "run/1", "run/2")
    step(inst.state_dir, "run/1", "review", 1)

    line = forecast_line(status(inst, capsys))

    assert line.count("run/1 2.5%") == 2, line
    assert "run/2" not in line
    assert "1 unrecorded" in line


def test_the_line_shows_a_track_reserved_before_the_reset_and_that_the_timers_were_read(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = installation(tmp_path, host)
    lay(host, history())
    lay_calls(host, "track_health", 1.0)
    keep_timer(host, tmp_path, monkeypatch, track="health", fires_in=timedelta(hours=1))

    line = forecast_line(status(inst, capsys))

    assert line.count("track_health 2.5%") == 2, line
    assert "timers read" in line
    assert "timers not read" not in line


def test_the_line_says_the_timers_were_not_read_when_systemctl_fails(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = installation(tmp_path, host)
    lay(host, history())
    lay_calls(host, "track_health", 1.0)
    failing = tmp_path / "failing" / "systemctl"
    failing.parent.mkdir()
    failing.write_text("#!/bin/sh\nexit 1\n")
    failing.chmod(0o755)
    monkeypatch.setenv("PATH", f"{failing.parent}:{os.environ['PATH']}")

    line = forecast_line(status(inst, capsys))

    assert "timers not read" in line
    assert "track_health" not in line


def test_the_line_comes_after_the_estimate_line(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path, host)
    lay(host, history())

    lines = status(inst, capsys)

    estimate = next(i for i, each in enumerate(lines) if "estimated (" in each)
    forecast = next(i for i, each in enumerate(lines) if "forecast:" in each)
    assert estimate + 1 == forecast, "\n".join(lines)


def test_no_line_is_printed_with_the_forecast_off(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    on = installation(tmp_path, host)
    lay(host, history())
    assert "forecast:" in forecast_line(status(on, capsys))

    off = installation(tmp_path, host, usage_forecast=False)
    lines = status(off, capsys)

    assert not any("forecast:" in each for each in lines)
    assert any("estimated (" in each for each in lines)


def test_no_line_is_printed_for_a_runtime_with_no_usage_window(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = installation(tmp_path, host)
    lay(host, history())
    assert "forecast:" in forecast_line(status(inst, capsys))

    monkeypatch.setattr(runtimes, "active", lambda: StandInRuntime())
    lines = status(inst, capsys)

    assert not any("forecast:" in each for each in lines)
    assert any("has no usage window" in each for each in lines)
