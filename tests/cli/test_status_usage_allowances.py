"""`abk status` prints which usage allowances are in force and the pairs behind them, no call."""

from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import build_parser
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.usage_allowances import ALLOWANCES_NAME, Calibrated, write_allowances
from tests.conftest import make_installation
from tests.usage_allowance_records import calibrated
from tests.usage_host import Host, payload, refused


def status_lines(
    tmp_path: Path,
    host: Host,
    capsys: pytest.CaptureFixture[str],
    found: dict[str, Calibrated],
    **limits: object,
) -> list[str]:
    """The lines of `abk status` with a reading held, the endpoint refusing and `found` kept."""
    runtimes = {"claude_code": {"limits": limits}}
    inst = make_installation(tmp_path / "planning", planning={"state_dir": "."}, runtimes=runtimes)
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    host.keep_in(inst.state_dir)
    host.keep_reading(timedelta(minutes=89), payload(session=0.0, weekly=65.0))
    refused(host, cooling=timedelta(minutes=3))
    write_allowances(inst.state_dir / ALLOWANCES_NAME, found)

    assert cli.cmd_status(build_parser().parse_args(["status"]), inst) == 0

    assert host.asked == 0
    return capsys.readouterr().out.splitlines()


def allowance_lines(lines: list[str]) -> list[str]:
    """The allowance lines, without the `[HH:MM:SS] ` the log puts before each."""
    return [line.split("] ", 1)[-1] for line in lines if "usage allowances:" in line]


def test_the_allowances_in_force_and_the_pairs_behind_them_are_printed(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    found = {"session": calibrated(9, 24), "weekly": calibrated(1, 24)}

    lines = status_lines(tmp_path, host, capsys, found)

    assert allowance_lines(lines) == [
        "usage allowances: session 9/unit (24 pairs), weekly 1/unit (24 pairs), calibrated"
    ]


def test_too_few_pairs_say_the_defaults_stand_and_how_many_are_needed(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    found = {"session": calibrated(None, 3), "weekly": calibrated(None, 3)}

    lines = status_lines(tmp_path, host, capsys, found)

    assert allowance_lines(lines) == ["usage allowances: defaults (3 pairs of 8 needed)"]


def test_windows_that_differ_are_named_one_by_one(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    found = {"session": calibrated(9, 24), "weekly": calibrated(None, 3)}

    lines = status_lines(tmp_path, host, capsys, found)

    assert allowance_lines(lines) == [
        "usage allowances: session 9/unit (24 pairs), weekly 2/unit default (3 pairs of 8 needed)"
    ]


def test_calibration_off_says_the_allowances_are_fixed(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    found = {"session": calibrated(9, 24), "weekly": calibrated(1, 24)}

    lines = status_lines(tmp_path, host, capsys, found, calibrate_usage_allowances=False)

    assert allowance_lines(lines) == ["usage allowances: fixed (calibration off)"]


def test_a_figure_cut_to_the_ceiling_or_raised_to_the_floor_is_marked(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    found = {"session": calibrated(40, 24), "weekly": calibrated(0, 24)}

    lines = status_lines(tmp_path, host, capsys, found)

    assert allowance_lines(lines) == [
        "usage allowances: session 20/unit (24 pairs, capped), "
        "weekly 1/unit (24 pairs, floor), calibrated"
    ]
