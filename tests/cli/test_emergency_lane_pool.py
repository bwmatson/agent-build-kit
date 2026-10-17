"""The build pool has a thread for the emergency lane: a priority-0 unit started in the lane
runs at once beside a full set of builds, and the lane's record names it for as long as it is
in progress.

The builder blocks each build until the test lets it go, as `test_tick_scheduling` does."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline import emergency_lane
from agent_build_kit.pipeline.units import MERGED, RUNNING
from tests.emergency_lane_support import lane_workspace
from tests.tick_pass import Builder, install_builder, isolate, stored, tick, warm_unit_graphs
from tests.waiting import wait_for

# Long enough never to trip when the pass does what the test waits for.
WAIT = 30

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    warm_unit_graphs(tmp_path)
    isolate(monkeypatch)
    monkeypatch.setattr(cli, "REFRESH_SECONDS", 0.05)


@pytest.fixture
def builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Builder:
    return install_builder(tmp_path, monkeypatch)


def pool_sizes(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """The thread counts of the pools the pass creates, as it creates them."""
    sizes: list[int] = []

    class Recording(ThreadPoolExecutor):
        def __init__(self, max_workers: int | None = None, thread_name_prefix: str = "") -> None:
            sizes.append(max_workers or 0)
            super().__init__(max_workers=max_workers, thread_name_prefix=thread_name_prefix)

    monkeypatch.setattr(cli, "ThreadPoolExecutor", Recording)
    return sizes


@pytest.mark.parametrize(
    ("extra", "restacks", "threads"),
    [(1, 2, 10), (3, 2, 14), (0, 2, 8), (1, 6, 10)],
    ids=["one", "three", "off", "more restacks"],
)
def test_the_pool_is_the_workers_and_the_lane_cap_for_each_live_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    builder: Builder,
    extra: int,
    restacks: int,
    threads: int,
) -> None:
    inst = lane_workspace(tmp_path, extra=extra, restacks=restacks)
    builder.store.upsert([stored("one/1")])
    sizes = pool_sizes(monkeypatch)

    assert tick(inst) == 0

    # Two projects (`app` and `platform`), four workers and the lane's cap in each.
    assert sizes == [threads]
    assert threads == (4 + extra) * 2


def run_blocked_pass(
    tmp_path: Path, builder: Builder, monkeypatch: pytest.MonkeyPatch, *, extra: int
) -> tuple[list[int], list[frozenset[str]]]:
    """Four blocking builds fill the workers; a priority-0 unit then turns up. Returns the
    builds in flight whenever the priority-0 unit's own build ran (or, when it was never
    started, at the moment the test gave up waiting for it) and the lane records seen then."""
    inst = lane_workspace(tmp_path, extra=extra)
    names = [f"block{n}/1" for n in range(4)]
    builder.store.upsert([stored(uid) for uid in names])
    release = threading.Event()
    in_flight: list[int] = []
    records: list[frozenset[str]] = []
    polls: list[int] = []

    def poll(inst, **kwargs) -> None:
        polls.append(1)
        if len(builder.started) >= 4 and "zero/1" not in {u.id for u in builder.store.all()}:
            builder.store.upsert([stored("zero/1", priority=0)])
        # The extra refreshes a pass that never starts the unit needs before giving up on it.
        if len(polls) > 12 and not release.is_set():
            in_flight.append(len([u for u in builder.store.all() if u.state == RUNNING]))
            records.append(emergency_lane.lane_units(inst.state_dir))
            release.set()

    def lane_build() -> None:
        in_flight.append(len([u for u in builder.store.all() if u.state == RUNNING]))
        records.append(emergency_lane.lane_units(inst.state_dir))
        release.set()

    monkeypatch.setattr(cli, "poll_all", poll)
    for uid in names:
        builder.scripts[uid] = lambda: wait_for(release.is_set, what="the release", timeout=WAIT)
    builder.scripts["zero/1"] = lane_build

    assert tick(inst) == 0
    return in_flight, records


def test_a_priority_zero_unit_runs_beside_four_blocked_builds_in_the_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, builder: Builder
) -> None:
    in_flight, records = run_blocked_pass(tmp_path, builder, monkeypatch, extra=1)

    assert "zero/1" in builder.started
    assert in_flight == [5]
    assert records == [frozenset({"zero/1"})]


def test_with_the_lane_off_the_fifth_build_is_not_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, builder: Builder
) -> None:
    in_flight, records = run_blocked_pass(tmp_path, builder, monkeypatch, extra=0)

    # The fifth build is not started beside the four; the unit builds alone once they end.
    assert in_flight == [4, 1]
    assert records == [frozenset(), frozenset()]
    assert builder.started.index("zero/1") > 3


def test_the_record_drops_a_unit_once_it_is_finished_or_gone(
    tmp_path: Path, builder: Builder
) -> None:
    inst = lane_workspace(tmp_path)
    builder.store.upsert([stored("zero/1", priority=0), stored("zero/2", priority=0)])
    for uid in ("zero/1", "zero/2"):
        emergency_lane.enter(inst.state_dir, builder.store.get(uid))
    builder.store.set_state("zero/1", RUNNING, branch="spec/zero/1")
    builder.store.set_state("zero/2", RUNNING, branch="spec/zero/2")
    assert emergency_lane.lane_units(inst.state_dir) == {"zero/1", "zero/2"}

    builder.store.set_state("zero/1", MERGED, pr=1)
    emergency_lane.prune(inst.state_dir, builder.store.all())
    assert emergency_lane.lane_units(inst.state_dir) == {"zero/2"}

    emergency_lane.prune(inst.state_dir, [])
    assert emergency_lane.lane_units(inst.state_dir) == frozenset()
