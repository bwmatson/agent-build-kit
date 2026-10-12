"""`abk status` prints the usage estimate from the reading it holds, with no call."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import build_parser
from agent_build_kit.cli import pipeline as cli
from tests.conftest import make_installation
from tests.usage_host import Host, payload

LIMITS = {
    "claude_code": {
        "limits": {"session": {"usage_pause_pct": 92}, "weekly": {"usage_pause_pct": 80}}
    }
}


def run_status(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str], weekly: float = 65.0
) -> str:
    """A reading 89 minutes old, a refusal two minutes ago and a cool-down in force."""
    inst = make_installation(tmp_path / "planning", planning={"state_dir": "."}, runtimes=LIMITS)
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    host.keep_in(inst.state_dir)
    host.keep_reading(timedelta(minutes=89), payload(session=0.0, weekly=weekly))
    host.seed(
        {
            "at": (datetime.now(UTC) - timedelta(minutes=2)).isoformat(),
            "caller": "guard",
            "outcome": "rate_limited",
            "status": 429,
            "latency_ms": 100,
            "headers": {"retry-after": "0"},
        }
    )
    kept = json.loads(host.cache.read_text())
    until = datetime.now(UTC) + timedelta(minutes=3)
    host.cache.write_text(json.dumps({**kept, "cooldown_until": until.isoformat()}))

    assert cli.cmd_status(build_parser().parse_args(["status"]), inst) == 0

    return capsys.readouterr().out


def test_status_prints_the_estimate_line_from_the_held_reading_and_the_lines_it_always_prints(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    out = run_status(tmp_path, host, capsys)

    assert "session ~0% estimated (0% read + 0% spent)" in out
    assert "weekly ~65% estimated (65% read + 0% spent)" in out
    assert "allowing starts" in out
    assert "89m old)" in out
    assert "session 0%/92%" in out
    assert "usage calls:" in out
    assert "usage cache: kept" in out
    assert host.asked == 0


def test_status_names_the_window_a_refusal_on_an_estimate_rests_on(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    out = run_status(tmp_path, host, capsys, weekly=78.0)

    assert "weekly ~78% estimated (78% read + 0% spent)" in out
    assert "is not 5 points under 80%" in out
    assert "allowing starts" not in out
    assert host.asked == 0
