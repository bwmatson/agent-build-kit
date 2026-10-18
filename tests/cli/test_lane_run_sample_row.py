"""The sample row and the two slot gauges report the slot occupancy, which counts a moved-base run
in the lane: `running` is the union and may exceed `cap`, `free_workers` is clamped at zero, and a
queued unit is not counted (spec: unit-scheduling).

A tick is driven as `test_restack_lane_tick` drives it: the poll hands the lane a run that blocks
on an event, the builds block on it too, and the pass sets it when a sample shows the figure the
test expects. A pass that never shows it ends when the bounded waits do.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.restack_lane import RestackLanes
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW
from tests.tick_pass import (
    Builder,
    install_builder,
    isolate,
    stored,
    tick,
    warm_unit_graphs,
    workspace,
)

pytestmark = pytest.mark.usefixtures("scripted_engine")

# Bounds a wait when the sample the test expects never comes; a pass that sees it never waits this.
WAIT = 5


class Scene:
    """A cap of four, `builds` blocking builds and one run in the lane, over a unit in review.
    `want` is the `running` count of the sample that ends them all."""

    def __init__(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, builds: int, queued: int = 0
    ) -> None:
        warm_unit_graphs(tmp_path)
        isolate(monkeypatch)
        monkeypatch.setattr(cli, "REFRESH_SECONDS", 0.05)
        self.inst: Installation = workspace(tmp_path, max_concurrent=4)
        self.builder: Builder = install_builder(tmp_path, monkeypatch)
        store: UnitStore = self.builder.store
        names = [f"block{n}/1" for n in range(builds)]
        store.upsert([stored(uid) for uid in names])
        store.upsert([stored("rev/1")])
        store.set_state("rev/1", IN_REVIEW, pr=9, branch="spec/rev/1")
        # Units that wait for a slot to build in: ready, but for the occupancy.
        store.upsert([stored(f"queued{n}/1") for n in range(queued)])
        self.begun = threading.Event()
        self.release = threading.Event()
        self.handed = False
        self.builds = builds
        self.want = builds + 1
        self.samples: list[spans.Sample] = []
        self.levels: list[tuple[str, int]] = []
        for uid in names:
            self.builder.scripts[uid] = self.hold
        record = spans.record_sample
        level = cli.telemetry.level

        def sampled(sample: spans.Sample, log: object) -> None:
            record(sample, log)  # type: ignore[arg-type]
            self.samples.append(sample)
            if sample.running >= self.want:
                self.release.set()

        def gauge(name: str, value: int, **attributes: str) -> None:
            self.levels.append((name, value))
            level(name, value, **attributes)

        monkeypatch.setattr(spans, "record_sample", sampled)
        monkeypatch.setattr(cli.telemetry, "level", gauge)
        monkeypatch.setattr(cli, "poll_all", self.poll)

    def hold(self) -> None:
        self.begun.wait(WAIT)
        self.release.wait(WAIT)

    def poll(self, inst: Installation, *, store: UnitStore, lane: RestackLanes) -> None:
        # The run comes once the builds are in: a run counts toward the occupancy, so it
        # would take a build's slot if it came first.
        if self.handed or len(self.builder.started) < self.builds:
            return
        self.handed = True

        def run() -> None:
            self.begun.set()
            self.release.wait(WAIT)

        lane.hand_over(store.get("rev/1"), run, claimed=False)

    def row_seeing(self, running: int) -> spans.Sample | None:
        assert tick(self.inst) == 0
        return next((row for row in self.samples if row.running == running), None)


def test_one_build_and_one_run_at_a_cap_of_four_read_as_two_running_and_two_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = Scene(tmp_path, monkeypatch, builds=1)

    row = scene.row_seeing(2)

    assert row is not None, [sample.running for sample in scene.samples]
    assert (row.cap, row.free_workers) == (4, 2)
    assert ("abk.slots.free", 2) in scene.levels


def test_four_builds_and_one_run_read_as_five_running_and_no_free_workers_not_a_negative_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = Scene(tmp_path, monkeypatch, builds=4)

    row = scene.row_seeing(5)

    assert row is not None, [sample.running for sample in scene.samples]
    assert (row.cap, row.free_workers) == (4, 0)
    assert min(sample.free_workers for sample in scene.samples) == 0
    assert ("abk.slots.free", 0) in scene.levels
    assert ("abk.slots.idle_with_ready", 0) in scene.levels


def test_a_queued_unit_is_not_counted_in_the_occupancy_of_the_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = Scene(tmp_path, monkeypatch, builds=4, queued=1)

    row = scene.row_seeing(5)

    assert row is not None, [sample.running for sample in scene.samples]
    assert row.queued == 1
    assert row.free_workers == 0
