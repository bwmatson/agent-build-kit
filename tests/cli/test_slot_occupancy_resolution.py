"""The slot occupancy, the `slots:` line of `abk status` and `abk explain` count a comment
rework in the resolution lane as a lane run and not as a build, and name what a unit is resolving
(spec: resolution-lane, the lane is named for what it does).

The lane is a real one over runs that block (`tests/lane_run_slots.py`), read from the same
process.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.cli.explain_cmd import cmd_explain
from agent_build_kit.pipeline.unit_store import Cause, FeedbackSource
from agent_build_kit.pipeline.units import RUNNING, project_key
from tests.cli.test_status_restacks import printed
from tests.emergency_lane_support import build
from tests.factories import new_unit
from tests.lane_run_slots import Slots

pytestmark = pytest.mark.usefixtures("scripted_engine")


def test_the_occupancy_leaves_out_a_comment_rework_running_in_the_lane() -> None:
    comment = new_unit(
        "c1/1",
        branch="spec/c1/1",
        state=RUNNING,
        cause=Cause.REWORK,
        feedback="[comment c1] remove this",
        feedback_source=FeedbackSource.REVIEW,
        moved_base_run=True,
    )
    other = new_unit("b1/1", branch="spec/b1/1", state=RUNNING)

    occupied = cli.slot_occupancy([comment, other], ["b1/1"], ["c1/1"])

    assert occupied == {project_key(other): {"b1/1"}}


def test_the_status_counts_a_comment_rework_as_resolving_and_not_in_the_slots_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with Slots(tmp_path, monkeypatch, [build("c1/1")]) as slots:
        slots.comment_runs("c1/1")
        slots.run("c1/1")
        capsys.readouterr()

        assert cli.cmd_status(argparse.Namespace(), slots.inst) == 0
        lines = printed(capsys)

    assert "resolving: 1 running, 0 waiting" in lines
    assert any("c1/1" in line and "resolving a comment" in line for line in lines)
    assert any(line.startswith("slots: 0/4") for line in lines)


def test_explain_names_a_comment_a_unit_is_resolving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with Slots(tmp_path, monkeypatch, [build("c1/1")]) as slots:
        slots.comment_runs("c1/1")
        slots.run("c1/1")
        capsys.readouterr()

        assert cmd_explain(argparse.Namespace(unit="c1/1", at=None), slots.inst) == 0
        out = capsys.readouterr().out

    assert "resolving a comment" in out


def test_explain_names_the_base_a_unit_is_resolving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with Slots(tmp_path, monkeypatch, [build("run1/1")], flagged=["run1/1"]) as slots:
        slots.run("run1/1")
        capsys.readouterr()

        assert cmd_explain(argparse.Namespace(unit="run1/1", at=None), slots.inst) == 0
        out = capsys.readouterr().out

    assert "resolving base main" in out
