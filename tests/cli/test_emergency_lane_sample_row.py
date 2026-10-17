"""The sample row after a start in the emergency lane keeps the normal `limit` and `cap`, counts
the lane's build as running, and sets the `abk.slots.emergency_used` gauge.

Four blocking builds fill the workers; a priority-0 unit then starts in the lane. The builds end
once the gauge has been set to the lane's use."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline import emergency_lane
from agent_build_kit.pipeline.units import IN_REVIEW
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from tests.emergency_lane_support import app_only_repos, lane_workspace
from tests.tick_pass import Builder, install_builder, isolate, stored, tick, warm_unit_graphs

pytestmark = pytest.mark.usefixtures("scripted_engine")

GAUGE = "abk.slots.emergency_used"
# Bounds the wait of a build when the gauge is never set; a pass that sets it never waits this.
WAIT = 5


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    warm_unit_graphs(tmp_path)
    isolate(monkeypatch)
    monkeypatch.setattr(cli, "REFRESH_SECONDS", 0.05)


@pytest.fixture
def builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Builder:
    return install_builder(tmp_path, monkeypatch)


@pytest.fixture
def gauge(monkeypatch: pytest.MonkeyPatch) -> tuple[list[int], threading.Event]:
    """The values the emergency gauge was set to, and an event set once it was set above 0."""
    values: list[int] = []
    in_use = threading.Event()
    real = cli.telemetry.level

    def level(name: str, value: int, **attributes: str) -> None:
        if name == GAUGE:
            values.append(value)
            if value:
                in_use.set()
        real(name, value, **attributes)

    monkeypatch.setattr(cli.telemetry, "level", level)
    return values, in_use


def samples(directory: Path) -> list[dict]:
    lines = [json.loads(line) for line in (directory / LEDGER_NAME).read_text().splitlines()]
    return [line for line in lines if line.get("kind") == "sample"]


def test_the_row_after_a_start_in_the_lane_counts_it_running_and_the_gauge_is_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    builder: Builder,
    gauge: tuple[list[int], threading.Event],
) -> None:
    values, in_use = gauge
    inst = lane_workspace(tmp_path, repos=app_only_repos(tmp_path))
    names = [f"block{n}/1" for n in range(4)]
    builder.store.upsert([stored(uid) for uid in names])

    def poll(inst, **kwargs) -> None:
        if len(builder.started) >= 4 and "zero/1" not in {u.id for u in builder.store.all()}:
            builder.store.upsert([stored("zero/1", priority=0)])

    monkeypatch.setattr(cli, "poll_all", poll)

    def hold() -> None:
        in_use.wait(WAIT)

    for uid in [*names, "zero/1"]:
        builder.scripts[uid] = hold

    assert tick(inst) == 0

    full = [row for row in samples(inst.state_dir) if row["running"] == 5]
    assert full, "no sample row saw the lane's build beside the four"
    assert (full[0]["cap"], full[0]["free_workers"], full[0]["limit"]) == (4, 0, 5)
    assert 0 in values
    assert 1 in values


def test_the_gauge_is_zero_when_no_unit_is_in_the_lane(
    builder: Builder, tmp_path: Path, gauge: tuple[list[int], threading.Event]
) -> None:
    values, _ = gauge
    inst = lane_workspace(tmp_path, repos=app_only_repos(tmp_path))
    builder.store.upsert([stored("one/1"), stored("two/1")])

    assert tick(inst) == 0

    assert values
    assert set(values) == {0}


def test_the_gauge_counts_a_lane_unit_that_is_in_review(
    builder: Builder, tmp_path: Path, gauge: tuple[list[int], threading.Event]
) -> None:
    values, _ = gauge
    inst = lane_workspace(tmp_path, repos=app_only_repos(tmp_path))
    builder.store.upsert([stored("zero/1", priority=0), stored("one/1")])
    builder.store.set_state("zero/1", IN_REVIEW, pr=1, branch="spec/zero/1")
    emergency_lane.enter(inst.state_dir, builder.store.get("zero/1"))

    assert tick(inst) == 0

    # The unit holds the lane for as long as it is in progress, review included.
    assert values
    assert set(values) == {1}
