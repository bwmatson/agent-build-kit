"""A full resolution lane overflows into the ordinary workers: an owed run the lane has no place
for starts in a free build worker, ranked after the units resuming a build and before those that
have never started (spec: resolution-lane, a full lane overflows into the ordinary workers).

The lane is a real one of one worker over runs that block until the test ends them
(`tests/lane_run_slots.py`); a round is `run_round` over the store, with the builds in flight
named by the test. A comment rework owed while the lane is full is queued in the lane.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.admission import admit
from agent_build_kit.pipeline.units import IN_REVIEW
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.cli.test_account_stack_cap_tick import lane_running, workspace
from tests.emergency_lane_support import build, fresh, seeded
from tests.lane_run_slots import Slots, as_comment_run, as_owed_comment
from tests.tick_pass import isolate

pytestmark = pytest.mark.usefixtures("scripted_engine")


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
