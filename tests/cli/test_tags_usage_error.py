"""`abk tags` says what to pass when given neither a change nor `--all`, or both
(spec: unit-scheduling)."""

from __future__ import annotations

import argparse

import pytest

from agent_build_kit.cli import build_parser
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from tests.cli.replan_driver import tasks_md

NEITHER = "abk tags: name a change, or pass --all for every change\n"
BOTH = "abk tags: give a change or --all, not both\n"


def tagged_change(installation: Installation) -> None:
    path = installation.changes_dir / "feature" / "tasks.md"
    path.parent.mkdir(parents=True)
    path.write_text(tasks_md(1))


def test_neither_a_change_nor_all_prints_the_usage_line_and_exits_2(
    installation: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    tagged_change(installation)

    status = cli.cmd_tags(argparse.Namespace(change=None, all=False), installation)

    captured = capsys.readouterr()
    assert status == 2
    assert captured.err == NEITHER
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert "TypeError" not in captured.err


def test_a_change_and_all_together_are_refused_and_nothing_is_checked(
    installation: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    tagged_change(installation)

    status = cli.cmd_tags(argparse.Namespace(change="feature", all=True), installation)

    captured = capsys.readouterr()
    assert status == 2
    assert captured.err == BOTH
    assert captured.out == ""
    assert "Traceback" not in captured.err


def test_the_tags_help_says_to_name_a_change_or_pass_all(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["tags", "--help"])

    out = " ".join(capsys.readouterr().out.split())
    assert "name a change, or --all for every change" in out
