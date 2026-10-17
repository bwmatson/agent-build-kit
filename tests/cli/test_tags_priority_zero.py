"""`abk tags` shows a group of priority 0 as it shows any priority other than 3."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from tests.cli.replan_driver import Replan
from tests.task_priority_files import tasks_md


def test_tags_prints_priority_zero_for_a_group_of_priority_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md("0", None))

    status = cli.cmd_tags(argparse.Namespace(change="feature", all=False), run.inst)

    lines = capsys.readouterr().out.splitlines()
    assert status == 0
    assert any("Group 1" in line and "(priority 0)" in line for line in lines)
    assert not any("Group 2" in line and "priority" in line for line in lines)
