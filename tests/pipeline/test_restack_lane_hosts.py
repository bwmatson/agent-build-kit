"""A lane's record names its host; one of another host is held, whatever pid it names."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.pipeline import host
from agent_build_kit.pipeline.events import build_claim
from agent_build_kit.pipeline.restack_lane import RestackLane, lane_record
from tests.branch_lock_fakes import dead_pid
from tests.factories import stored_unit
from tests.restack_lane_fakes import WAIT, Restacks


@pytest.fixture(autouse=True)
def on_box(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host, "this_host", lambda: "box")


def write_record(state: Path, **fields: object) -> None:
    held = [{"unit": "feature/1", "base": "main", "status": "running", "since": "t"}]
    record = {"pid": dead_pid(), "units": held, **fields}
    (state / "restacks-abc.json").write_text(json.dumps(record))


def test_a_record_of_another_host_is_held_though_its_pid_is_dead_here(tmp_path: Path) -> None:
    write_record(tmp_path, host="other")

    assert [entry["unit"] for entry in lane_record(tmp_path)] == ["feature/1"]


def test_a_record_of_this_host_with_a_dead_pid_and_one_without_a_host_are_not_held(
    tmp_path: Path,
) -> None:
    write_record(tmp_path, host="box")
    assert lane_record(tmp_path) == []

    write_record(tmp_path)
    assert lane_record(tmp_path) == []


def test_the_record_a_lane_writes_carries_the_host(tmp_path: Path) -> None:
    restacks = Restacks()
    record = tmp_path / "restacks-abc.json"
    lane = RestackLane(
        1,
        move=restacks,
        claim=build_claim(tmp_path / "locks"),
        owed=lambda graph: (),
        record=record,
    )
    with lane:
        lane.hand_over(stored_unit("feature/1", change="feature"))
        assert restacks.begun["feature/1"].wait(WAIT)
        written = json.loads(record.read_text())
        restacks.release_all()
        lane.drain()

    assert written["host"] == "box"
