"""A comment rework running in the resolution lane is not a build: it is counted by no build
worker count, so it never delays a build or a resume, and a full `max_concurrent_stacks` never
delays it (spec: resolution-lane, one lane resolves what an open pull request waits on).

The lane is a real one over runs that block until the test ends them (`tests/lane_run_slots.py`);
a round is `run_round` over the store, with the builds in flight named by the test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.emergency_lane_support import build, fresh
from tests.lane_run_slots import Slots

pytestmark = pytest.mark.usefixtures("scripted_engine")


def builds(count: int) -> list[str]:
    return [f"b{n}/1" for n in range(1, count + 1)]


def test_a_comment_rework_in_the_lane_leaves_every_build_worker_to_the_ready_units(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    units = [build("c1/1"), *(fresh(f"r{n}/1") for n in range(1, 6))]
    with Slots(tmp_path, monkeypatch, units) as slots:
        slots.comment_runs("c1/1")
        slots.run("c1/1")

        assert len(slots.started()) == 4, "all four workers, the lane's run takes none"


def test_a_comment_rework_in_the_lane_is_not_in_the_slot_occupancy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    units = [build("b1/1"), build("c1/1")]
    with Slots(tmp_path, monkeypatch, units) as slots:
        slots.comment_runs("c1/1")
        slots.run("c1/1")

        assert slots.lanes.running == ["c1/1"]
        assert slots.occupancy(["b1/1"]) == {"b1/1"}


def test_a_comment_rework_starts_in_the_lane_beside_a_full_set_of_builds_and_they_do_not_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    units = [*(build(uid) for uid in builds(4)), build("c1/1"), fresh("r1/1")]
    with Slots(tmp_path, monkeypatch, units) as slots:
        slots.comment_runs("c1/1")
        slots.run("c1/1")

        assert slots.lanes.running == ["c1/1"]
        assert slots.occupancy(builds(4)) == {*builds(4)}
        assert slots.started(builds(4)) == [], "four builds still fill the four workers"

        slots.end("c1/1")

        assert slots.started(builds(4)) == []


def test_a_resume_takes_the_worker_a_comment_rework_in_the_lane_leaves_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `res/1` is running with a thread and no run holding it: a resume.
    units = [build("c1/1"), build("res/1")]
    with Slots(tmp_path, monkeypatch, units, cap=1) as slots:
        slots.comment_runs("c1/1")
        slots.run("c1/1")

        assert slots.started() == ["res/1"]
