"""`abk status` shows a fresh reading from Claude Code's own cache with its age once, no call."""

from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import build_parser
from agent_build_kit.cli import pipeline as cli
from tests.conftest import make_installation
from tests.usage_host import Host, payload


def test_status_ends_the_usage_line_with_the_block_s_source_and_age_once(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = make_installation(
        tmp_path / "planning", planning={"state_dir": "."}, runtimes={"claude_code": {}}
    )
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    host.keep_in(inst.state_dir)
    host.keep_reading(timedelta(minutes=40), payload(session=90.0))
    host.keep_editor_reading(timedelta(minutes=6))

    assert cli.cmd_status(build_parser().parse_args(["status"]), inst) == 0

    shown = capsys.readouterr().out.splitlines()
    (line,) = [each for each in shown if "usage: " in each and "claude.json" in each]
    assert line.endswith("(claude.json, 6m old)")
    assert line.count("m old") == 1
    assert host.asked == 0
