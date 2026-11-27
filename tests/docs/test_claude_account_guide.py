"""The commands the how-to for a second Claude Code account shows are real
(spec: claude-account)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit.cli import build_parser

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "docs" / "claude-code-second-account.md"


def guide_text() -> str:
    assert GUIDE.is_file(), f"{GUIDE} does not exist"
    return GUIDE.read_text()


def test_every_abk_command_the_guide_shows_is_a_real_subcommand(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shown = set(re.findall(r"\babk ([a-z][a-z-]*)", guide_text()))

    assert {"doctor", "status"} <= shown
    for command in sorted(shown):
        with pytest.raises(SystemExit) as stopped:
            build_parser().parse_args([command, "--help"])
        assert stopped.value.code == 0, f"`abk {command}` is not a subcommand"
    capsys.readouterr()
