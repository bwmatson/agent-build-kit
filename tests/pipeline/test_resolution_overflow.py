"""A full resolution lane overflows into the ordinary workers: an owed run the lane has no place
for starts in a free build worker, ranked after the units resuming a build and before those that
have never started (spec: resolution-lane, a full lane overflows into the ordinary workers).

The lane is a real one of one worker over runs that block until the test ends them
(`tests/lane_run_slots.py`); a round is `run_round` over the store, with the builds in flight
named by the test. A comment rework owed while the lane is full is queued in the lane.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.admission import admit
from agent_build_kit.pipeline.unit_store import Starting
from agent_build_kit.pipeline.units import IN_REVIEW
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.cli.test_account_stack_cap_tick import lane_running, workspace
from tests.emergency_lane_support import build, fresh, seeded
from tests.lane_run_slots import Slots, as_comment_run, as_owed_comment
from tests.tick_pass import isolate

pytestmark = pytest.mark.usefixtures("scripted_engine")


def test_a_full_lane_and_a_free_worker_start_the_owed_rework_in_the_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    units = [build("c1/1"), build("c2/1", IN_REVIEW)]
    with Slots(tmp_path, monkeypatch, units, restacks=1) as slots:
        slots.comment_runs("c1/1")
        slots.run("c1/1")
        slots.owed_comments("c2/1")
        assert slots.lanes.waiting == ["c2/1"], "the lane has no place for it"

        assert slots.started() == ["c2/1"]

        assert slots.store.get("c2/1").feedback, "it is the same rework, with the words to rework"
        assert slots.lanes.running == ["c1/1"], "the overflow run is not a lane run"


def test_the_overflow_run_is_not_started_again_when_the_lane_has_room(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    units = [build("c1/1"), build("c2/1", IN_REVIEW)]
    with Slots(tmp_path, monkeypatch, units, restacks=1) as slots:
        slots.comment_runs("c1/1")
        slots.run("c1/1")
        slots.owed_comments("c2/1")
        assert slots.started() == ["c2/1"]
        # Admission marks the unit it let start; the lane's scan leaves it to its worker.
        marker = Starting(worker="tick-1", until=datetime.now(UTC) + timedelta(minutes=10))
        slots.store.set_starting("c2/1", marker)
        slots.lanes.scan(slots.store.all())
        assert slots.lanes.waiting == [], "the scan did not queue it again"

        slots.end("c1/1")

        assert slots.runs.started == ["c1/1"], "the lane did not take the run the worker has"
        assert slots.lanes.waiting == []


def test_a_dry_round_names_the_overflow_run_and_leaves_the_lane_queue_as_it_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    units = [build("c1/1"), build("c2/1", IN_REVIEW)]
    with Slots(tmp_path, monkeypatch, units, restacks=1) as slots:
        slots.comment_runs("c1/1")
        slots.run("c1/1")
        slots.owed_comments("c2/1")

        ready = cli.run_round(
            slots.inst,
            slots.store,
            building=(),
            only=frozenset(),
            submit=True,
            lane=slots.lanes,
            dry_run=True,
        )

        assert [unit.id for unit in ready] == ["c2/1"]
        assert slots.lanes.waiting == ["c2/1"], "a dry round writes no state"


def test_an_overflow_run_in_a_worker_holds_it_for_another_tick_once_its_marker_lapsed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `c2/1` runs in a worker of another tick: stored as a comment run, its branch locked, no
    # start marker, and no live record of the lane naming it.
    units = [build("c2/1", IN_REVIEW), fresh("r1/1")]
    with Slots(tmp_path, monkeypatch, units, cap=1) as slots:
        slots.comment_runs("c2/1")
        with branch_lock(slots.store.get("c2/1").branch, root=slots.inst.locks_dir):
            assert slots.started() == [], "the one worker is the overflow run's"
            admitted = admit(
                slots.inst,
                slots.store,
                [slots.store.get("r1/1")],
                worker="tick-2",
                now=spans.clock.now(),
                ttl=timedelta(minutes=10),
            )

            assert admitted == []


def test_the_overflow_run_counts_toward_the_stacks_and_not_the_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    units = [build("c1/1"), build("c2/1", IN_REVIEW), fresh("r1/1")]
    with Slots(tmp_path, monkeypatch, units, restacks=1, cap=1) as slots:
        slots.comment_runs("c1/1")
        slots.run("c1/1")
        slots.owed_comments("c2/1")

        assert slots.started() == ["c2/1"], "the one worker goes to the overflow run, not r1"
        assert slots.occupancy(["c2/1"]) == {"c2/1"}
        assert slots.started(["c2/1"]) == []


def test_the_overflow_run_takes_no_place_of_max_units_in_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `c1/1` and `c2/1` are in progress already; the third place is the new unit's.
    units = [build("c1/1"), build("c2/1", IN_REVIEW), fresh("r1/1")]
    with Slots(tmp_path, monkeypatch, units, restacks=1, places=3) as slots:
        slots.comment_runs("c1/1")
        slots.run("c1/1")
        slots.owed_comments("c2/1")

        assert slots.started() == ["c2/1", "r1/1"]


def test_the_owed_runs_take_the_free_workers_in_the_order_they_were_first_seen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    units = [
        build("c1/1"),
        build("b1/1"),
        build("b2/1"),
        build("c2/1", IN_REVIEW),
        build("c3/1", IN_REVIEW),
    ]
    with Slots(tmp_path, monkeypatch, units, restacks=1, cap=3) as slots:
        slots.comment_runs("c1/1")
        slots.run("c1/1")
        # Seen in the reverse of the store's order.
        slots.owed_comments("c3/1", "c2/1")
        building = ["b1/1", "b2/1"]

        assert slots.started(building) == ["c3/1"], "one worker is free, and c3 was seen first"
        assert slots.started([*building, "c3/1"]) == [], "no worker is free: c2 waits"


@pytest.mark.parametrize(
    ("workers", "starts"),
    [(1, ["res/1"]), (2, ["res/1", "c2/1"]), (3, ["res/1", "c2/1", "r1/1"])],
)
def test_a_resume_then_the_overflow_run_then_a_new_unit_take_the_free_workers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, workers: int, starts: list[str]
) -> None:
    # `res/1` is running with a thread and no run holding it: a resume.
    units = [build("c1/1"), build("res/1"), build("c2/1", IN_REVIEW), fresh("r1/1")]
    with Slots(tmp_path, monkeypatch, units, restacks=1, cap=workers) as slots:
        slots.comment_runs("c1/1")
        slots.run("c1/1")
        slots.owed_comments("c2/1")

        assert slots.started() == starts


def test_an_overflow_run_counts_toward_the_accounts_stack_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolate(monkeypatch)
    # The lane's run has its thread, so nothing reclaims it for want of a lock.
    monkeypatch.setattr(cli, "has_thread", lambda inst, unit_id: True)
    inst = workspace(
        tmp_path,
        account={"max_concurrent_stacks": 1},
        project={"max_concurrent_resolutions": 1},
    )
    units = [
        build("app-c1/1", repo="app"),
        build("app-c2/1", IN_REVIEW, repo="app"),
        fresh("platform-new/1", repo="platform"),
    ]
    store = seeded(inst, tmp_path, units)
    as_comment_run(store, "app-c1/1")
    as_owed_comment(store, "app-c2/1")

    with lane_running(inst, store, "app-c1/1") as lanes:
        lanes.hand_over(store.get("app-c2/1"), lambda: None, claimed=False)
        ready = cli.run_round(inst, store, building=(), only=frozenset(), submit=True, lane=lanes)

    assert [unit.id for unit in ready] == ["app-c2/1"], "the account's one stack is its run's"
