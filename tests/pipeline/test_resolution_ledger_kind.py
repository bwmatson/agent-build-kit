"""The lane's per-project record and the `restack` lines of the usage ledger carry the kind of
run being resolved: `base` for a restack or a moved-base run, `comment` for a rework (spec:
resolution-lane, the lane is named for what it does)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.resolution_lane import lane_record
from tests.emergency_lane_support import build
from tests.graph.test_restack_lane_prepare import Scene
from tests.lane_run_slots import Slots
from tests.moved_base_fakes import restack_lines
from tests.tick_driver import OTHER, Setup, make_setup

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture
def graph(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Setup:
    """A tick over one unit's thread with its edges faked (`tests/tick_driver.py`)."""
    return make_setup(tmp_path, monkeypatch)


def test_the_lane_record_names_a_comment_rework_as_a_comment_and_a_moved_base_run_as_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    units = [build("c1/1"), build("run1/1")]
    with Slots(tmp_path, monkeypatch, units, flagged=["run1/1"]) as slots:
        slots.comment_runs("c1/1")
        slots.run("c1/1", "run1/1")

        kinds = {entry["unit"]: entry["resolving"] for entry in lane_record(slots.inst.state_dir)}

    assert kinds == {"c1/1": "comment", "run1/1": "base"}


def test_the_lane_worker_says_what_it_is_resolving_to_the_code_it_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    units = [build("c1/1"), build("run1/1")]
    seen: dict[str, str] = {}
    with Slots(tmp_path, monkeypatch, units, flagged=["run1/1"]) as slots:
        slots.comment_runs("c1/1")
        for unit_id in ("c1/1", "run1/1"):

            def work(unit_id: str = unit_id) -> None:
                seen[unit_id] = spans.resolving.get()

            slots.lanes.hand_over(slots.store.get(unit_id), work, claimed=False)
        slots.lanes.drain()

    assert seen == {"c1/1": "comment", "run1/1": "base"}


def test_a_restack_line_written_in_the_lane_carries_the_kind_of_run(
    graph: Setup, tmp_path: Path
) -> None:
    scene = Scene(graph, tmp_path)
    scene.told_its_base_moved()
    written = len(restack_lines(graph.inst))

    scene.lane_moves()

    lines = [line for line in restack_lines(graph.inst)[written:] if line["unit"] == OTHER]
    assert lines, "the lane's move wrote a restack line"
    assert {line["resolving"] for line in lines} == {"base"}
