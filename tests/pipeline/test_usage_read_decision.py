"""The usage endpoint is asked only when a fresh reading could change a decision.

A refusal made on a reading of a window that has not reset stands without a call;
an allowance stands while the usage could not have reached the threshold since the
reading; a reading of a window that has reset, or none at all, is asked for. The
endpoint is never asked more often than the interval allows, and the status command
calls it only when told to (spec: usage-pause).

Only the endpoint and the home directory are faked (`tests/usage_host.py`).
"""

import re
from argparse import Namespace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit import config as config_module
from agent_build_kit.cli import build_parser
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.pipeline.usage_guard import decide_start
from tests.conftest import make_installation
from tests.usage_host import Host, payload

MINUTES = timedelta(minutes=1)


def configure(**limits: object) -> None:
    """The Claude limits an installation sets, over the defaults."""
    config_module.activate(
        WorkspaceConfig.model_validate({"runtimes": {"claude_code": {"limits": limits}}}), None
    )


def pause_at(percent: int, **window: object) -> dict:
    return {
        "session": {"usage_pause_pct": percent, **window},
        "weekly": {"usage_pause_pct": percent, **window},
    }


@pytest.fixture(autouse=True)
def ninety_two(host: Host) -> None:
    """A threshold of ninety-two on both windows, which does not ramp."""
    configure(**pause_at(92))


def called(host: Host, ago: timedelta, outcome: str = "ok") -> None:
    """The record shows a call to the endpoint `ago` ago."""
    host.seed(
        {
            "at": (datetime.now(UTC) - ago).isoformat(),
            "caller": "guard",
            "outcome": outcome,
            "status": 200 if outcome == "ok" else None,
            "latency_ms": 100,
            "headers": {},
        }
    )


# --- 1.1 what settles a decision ------------------------------------------------------


def test_far_from_the_threshold_a_start_is_allowed_from_an_old_reading_without_a_call(
    host: Host,
) -> None:
    host.keep_reading(
        timedelta(minutes=20), payload(session=20.0, session_resets_in=timedelta(hours=3))
    )

    decision = decide_start()

    assert decision.may_start
    assert host.asked == 0


def test_a_reading_over_the_threshold_before_its_reset_refuses_until_the_reset_without_a_call(
    host: Host,
) -> None:
    host.keep_reading(
        timedelta(minutes=40), payload(session=95.0, session_resets_in=timedelta(hours=2))
    )

    decision = decide_start()

    assert not decision.may_start
    assert host.asked == 0
    assert decision.resume_at is not None
    assert abs(decision.resume_at - (datetime.now(UTC) + timedelta(hours=2))) < 2 * MINUTES


def test_a_refusal_stands_until_the_threshold_is_worked_out_to_reach_the_reading(
    host: Host,
) -> None:
    """The threshold rises from 70 to 95 over the last 75 minutes of the session; the
    reading, 80, is room (with the resume buffer) when it reaches 85, thirty minutes
    before the reset."""
    configure(**pause_at(70, usage_pause_ceiling_pct=95))
    host.keep_reading(
        timedelta(minutes=40), payload(session=80.0, session_resets_in=timedelta(minutes=100))
    )

    decision = decide_start()

    assert not decision.may_start
    assert host.asked == 0
    assert decision.resume_at is not None
    assert abs(decision.resume_at - (datetime.now(UTC) + timedelta(minutes=70))) < 2 * MINUTES


def test_a_reading_with_less_headroom_than_could_have_been_added_asks_the_endpoint(
    host: Host,
) -> None:
    """Twenty minutes at the floor of a fifth of a point is four points, and the margin
    two: ninety leaves less than that under ninety-two."""
    configure(**pause_at(92), usage_climb_floor=0.2, usage_climb_margin_pct=2)
    host.keep_reading(
        timedelta(minutes=20), payload(session=90.0, session_resets_in=timedelta(hours=3))
    )
    called(host, timedelta(hours=3))
    host.answers = [payload(session=91.0)]

    decide_start()

    assert host.asked == 1


@pytest.mark.parametrize("window", ["session", "weekly"])
def test_a_reading_of_a_window_that_has_reset_asks_the_endpoint(host: Host, window: str) -> None:
    gone = timedelta(minutes=-10)
    host.keep_reading(
        timedelta(minutes=40),
        payload(
            session=95.0,
            weekly=95.0,
            session_resets_in=gone if window == "session" else timedelta(hours=2),
            weekly_resets_in=gone if window == "weekly" else timedelta(days=3),
        ),
    )
    called(host, timedelta(hours=3))
    host.answers = [payload(session=3.0, weekly=3.0)]

    decision = decide_start()

    assert host.asked == 1
    assert decision.may_start


def test_with_no_reading_the_endpoint_is_asked(host: Host) -> None:
    host.answers = [payload(session=10.0)]

    decision = decide_start()

    assert host.asked == 1
    assert decision.may_start


# --- 1.2 the minimum interval -------------------------------------------------------


def test_a_decision_that_needs_a_reading_inside_the_interval_refuses_for_the_time_left(
    host: Host,
) -> None:
    host.keep_reading(
        timedelta(minutes=40), payload(session=90.0, session_resets_in=timedelta(hours=3))
    )
    called(host, timedelta(minutes=2), "timeout")

    decision = decide_start()

    assert not decision.may_start
    assert host.asked == 0
    assert "interval" in decision.reason.lower()
    assert decision.resume_at is not None
    left = decision.resume_at - datetime.now(UTC)
    assert timedelta(minutes=12) < left <= timedelta(minutes=13, seconds=5)


def test_an_endpoint_that_was_asked_a_quarter_hour_ago_may_be_asked_again(host: Host) -> None:
    host.keep_reading(
        timedelta(minutes=40), payload(session=90.0, session_resets_in=timedelta(hours=3))
    )
    called(host, timedelta(minutes=16), "timeout")
    host.answers = [payload(session=91.0)]

    decide_start()

    assert host.asked == 1


# --- 1.3 the status command ---------------------------------------------------------


def status_args(*, refresh: bool) -> Namespace:
    """`abk status`, as the command line parses it."""
    return build_parser().parse_args(["status", *(["--refresh"] if refresh else [])])


def status(tmp_path: Path, host: Host, *, refresh: bool) -> None:
    inst = make_installation(tmp_path / "planning", planning={"state_dir": "."})
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    host.keep_in(inst.state_dir)
    host.keep_reading(timedelta(minutes=20), payload(session=21.0))
    assert cli.cmd_status(status_args(refresh=refresh), inst) == 0


def usage_line(out: str) -> str:
    (shown,) = [text for text in out.splitlines() if re.match(r"(\[[\d:]+\] )?usage: ", text)]
    return re.sub(r"^\[[\d:]+\] ", "", shown)


def test_the_status_command_prints_the_held_reading_its_age_and_source_and_calls_nothing(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    status(tmp_path, host, refresh=False)

    shown = usage_line(capsys.readouterr().out)
    assert "21%" in shown
    assert re.search(r"\b2[01] ?m", shown), "the reading's age is not shown"
    assert "cache" in shown
    assert host.asked == 0


def test_the_status_command_with_no_held_reading_calls_nothing(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = make_installation(tmp_path / "planning", planning={"state_dir": "."})
    host.keep_in(inst.state_dir)

    assert cli.cmd_status(status_args(refresh=False), inst) == 0

    assert usage_line(capsys.readouterr().out) == "usage: unknown"
    assert host.asked == 0


def test_the_status_command_asked_to_refresh_calls_the_endpoint(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    host.answers = [payload(session=33.0)]

    status(tmp_path, host, refresh=True)

    assert host.asked == 1
    assert "33%" in usage_line(capsys.readouterr().out)


def test_a_refresh_inside_the_interval_makes_no_call(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = make_installation(tmp_path / "planning", planning={"state_dir": "."})
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    host.keep_in(inst.state_dir)
    host.keep_reading(timedelta(minutes=40), payload(session=21.0))
    called(host, timedelta(minutes=2), "timeout")

    assert cli.cmd_status(status_args(refresh=True), inst) == 0

    assert host.asked == 0
    assert "21%" in usage_line(capsys.readouterr().out)
