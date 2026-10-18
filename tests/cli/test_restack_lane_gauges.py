"""The lane's two counts are gauges of their own, set where the slot gauges are, with no unit or
change attribute; a restack in the lane counts toward the slot gauges' occupancy.

A tick is driven as `test_restack_lane_tick` drives it: the poll hands the lane a restack that
blocks on an event, and the pass sets it when it next asks the lane to say when a restack ends,
which it does once the first sample's gauges are set, so they are read with the restack running.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.restack_lane import RestackLane
from tests.cli.test_restack_lane_tick import Scene

pytestmark = pytest.mark.usefixtures("scripted_engine")


def test_the_restack_gauges_are_set_with_the_slot_gauges_and_carry_no_attribute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = Scene(tmp_path, monkeypatch)
    scene.release_on_build = False
    levels: list[tuple[str, int, dict[str, str]]] = []
    real_level = cli.telemetry.level
    record = spans.record_sample
    finished = RestackLane.finished
    samples: list[Any] = []

    def level(name: str, value: int, **attributes: str) -> None:
        levels.append((name, value, attributes))
        real_level(name, value, **attributes)

    def sampled(sample: spans.Sample, log: Any) -> None:
        record(sample, log)
        samples.append(sample)

    def asked_when_one_ends(lane: RestackLane) -> Any:
        if samples:
            scene.release.set()
        return finished(lane)

    monkeypatch.setattr(cli.telemetry, "level", level)
    monkeypatch.setattr(spans, "record_sample", sampled)
    monkeypatch.setattr(RestackLane, "finished", asked_when_one_ends)

    assert scene.tick() == 0

    def first(name: str) -> tuple[int, dict[str, str]] | None:
        found = ((value, attributes) for gauge, value, attributes in levels if gauge == name)
        return next(found, None)

    assert first("abk.restacks.running") == (1, {})
    assert first("abk.restacks.waiting") == (0, {})
    # The slot gauges are the occupancy's, as the sample row's free workers are: the run counts.
    assert first("abk.slots.free") == (samples[0].free_workers, {})
    assert samples[0].free_workers == 1
