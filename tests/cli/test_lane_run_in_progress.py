"""A moved-base run counts toward slot occupancy and not toward a second figure: the limit on
units in progress is read as before, a run starts whatever it is, and a ready unit held back by the
occupancy reads as waiting for a slot, not for room in the queue (spec: unit-scheduling).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, project_counts, project_key
from tests.cli.test_status_restacks import printed
from tests.emergency_lane_support import build, fresh
from tests.lane_run_slots import Slots

pytestmark = pytest.mark.usefixtures("scripted_engine")


def test_a_run_starts_at_the_limit_on_units_in_progress_and_the_count_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    units = [build("rev/1", IN_REVIEW), build("run1/1"), fresh("new/1")]
    with Slots(tmp_path, monkeypatch, units, places=2, flagged=["run1/1"]) as slots:
        before = project_counts(slots.store.all())

        slots.run("run1/1")

        assert project_counts(slots.store.all()) == before
        assert before[project_key(slots.store.get("run1/1"))] == 2
        assert slots.occupancy() == {"run1/1"}
        assert slots.started() == []
        assert slots.reasons()["new/1"] == "queue_full"


def test_a_run_beside_a_build_is_not_a_second_unit_in_progress_for_the_unit_that_follows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    units = [build("b1/1"), build("run1/1"), fresh("new/1")]
    with Slots(tmp_path, monkeypatch, units, places=3, flagged=["run1/1"]) as slots:
        slots.run("run1/1")

        assert slots.occupancy(["b1/1"]) == {"b1/1", "run1/1"}
        assert slots.started(["b1/1"]) == ["new/1"]


def test_a_blocked_started_unit_is_still_listed_as_not_counted_beside_a_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    units = [
        build("rev/1", IN_REVIEW),
        build("run1/1"),
        build("blocked/1", PLANNED, depends_on=("far/1",)),
        build("far/1", IN_REVIEW, repo="platform"),
    ]
    with Slots(tmp_path, monkeypatch, units, places=2, flagged=["run1/1"]) as slots:
        slots.run("run1/1")

        capsys.readouterr()
        assert cli.cmd_status(argparse.Namespace(), slots.inst) == 0
        (line,) = (line for line in printed(capsys) if "queue is full:" in line)

        assert "2 units in progress, limit 2" in line
        assert "1 blocked not counted" in line
        assert slots.occupancy() == {"run1/1"}


def test_a_ready_unit_held_back_by_the_occupancy_at_the_cap_reads_as_waiting_for_a_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    units = [build("b1/1"), build("run1/1"), fresh("r1/1")]
    with Slots(tmp_path, monkeypatch, units, cap=2, flagged=["run1/1"]) as slots:
        slots.run("run1/1")

        assert slots.started(["b1/1"]) == []

        assert slots.reasons()["r1/1"] == "slot"
