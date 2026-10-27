"""The emergency lane does not start a unit whose groups are all held (spec: external-work)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.external_file import HELD, RELEASED, write_holds
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW
from tests.emergency_lane_support import build, fresh, lane_workspace, seeded, started_by_round
from tests.external_support import hold
from tests.tick_pass import isolate

pytestmark = pytest.mark.usefixtures("scripted_engine")

WORKERS = [f"run{n}/1" for n in range(4)]


@pytest.fixture(autouse=True)
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate(monkeypatch)


def held_world(tmp_path: Path, *, released: bool) -> tuple[Installation, UnitStore]:
    """Every worker and place busy, and a priority-0 unit whose group has a hold."""
    inst = lane_workspace(tmp_path)
    store = seeded(
        inst,
        tmp_path,
        [
            *(build(uid) for uid in WORKERS),
            build("rev/1", IN_REVIEW),
            fresh("feature/1", priority=0),
        ],
    )
    # No `tasks.md`, so the round has no plan to make that would replace the planned unit.
    folder = inst.changes_dir / "feature"
    folder.mkdir(parents=True)
    write_holds(folder, [hold((1,), status=RELEASED if released else HELD)])
    return inst, store


def test_a_held_priority_zero_unit_is_not_handed_out_past_full_workers(tmp_path: Path) -> None:
    inst, store = held_world(tmp_path, released=False)

    assert started_by_round(inst, store, building=WORKERS) == []


def test_the_same_unit_with_its_hold_released_is_handed_out_by_the_lane(tmp_path: Path) -> None:
    inst, store = held_world(tmp_path, released=True)

    assert started_by_round(inst, store, building=WORKERS) == ["feature/1"]
