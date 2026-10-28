"""A unit waiting to resume that gets no worker holds back the emergency lane's starts of its own
project only (spec: usage-pause-slots, units waiting to resume are resumed in start order, ahead
of new starts). A waiting unit is `running` with a thread, no lock and no pause; `platform` runs
beside `app`, each with its own workers."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline import emergency_lane
from agent_build_kit.pipeline.units import RUNNING
from tests.cli.usage_pause_support import (
    isolate_round,
    started_by,
    unit,
    with_threads,
    workspace,
)

URGENT = "urgent/1"


def waiting_and_urgent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, urgent_repo: str):
    """`app` has two units waiting to resume for its one worker; the priority-0 `urgent/1` is
    new, in `urgent_repo`, whose own worker is busy so that only the lane could start it."""
    isolate_round(tmp_path, monkeypatch)
    inst, store = workspace(
        tmp_path,
        [
            unit("first/1", "app", priority=1),
            unit("second/1", "app", priority=2),
            unit("busy/1", "platform"),
            unit(URGENT, urgent_repo, priority=0),
        ],
        workers=1,
    )
    for uid in ("first/1", "second/1"):
        store.set_state(uid, RUNNING, branch=f"spec/{uid}")
    store.set_state("busy/1", RUNNING, branch="spec/busy/1")
    with_threads(monkeypatch, "first/1", "second/1")
    return inst, store


def test_a_lane_start_waits_for_the_units_waiting_to_resume_in_its_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst, store = waiting_and_urgent(tmp_path, monkeypatch, urgent_repo="app")

    started = started_by(inst, store, building=("busy/1",))

    assert started == ["first/1"]
    assert URGENT not in emergency_lane.lane_units(inst.state_dir)


def test_a_lane_start_in_another_project_goes_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst, store = waiting_and_urgent(tmp_path, monkeypatch, urgent_repo="platform")

    started = started_by(inst, store, building=("busy/1",))

    assert started == ["first/1", URGENT]
    assert URGENT in emergency_lane.lane_units(inst.state_dir)
