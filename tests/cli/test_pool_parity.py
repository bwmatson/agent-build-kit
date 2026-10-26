"""The thread pool's admission (`run_round`) and the pure occupancy function agree on the same
fixtures: the units the round hands out are the free slots the function reports."""

from pathlib import Path

import pytest

from agent_build_kit.pipeline.occupancy import Limits, free, occupied
from agent_build_kit.pipeline.units import ProjectKey
from tests.emergency_lane_support import build, fresh, lane_workspace, seeded, started_by_round
from tests.fake_clock import START
from tests.tick_pass import isolate

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture(autouse=True)
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate(monkeypatch)


@pytest.mark.parametrize("running", [0, 1, 2, 3, 4])
def test_the_round_starts_as_many_units_as_the_function_reports_free(
    tmp_path: Path, running: int
) -> None:
    inst = lane_workspace(tmp_path, workers=3, places=9, extra=0)
    held = [f"run{n}/1" for n in range(running)]
    waiting = [f"wait{n}/1" for n in range(4)]
    store = seeded(
        inst, tmp_path, [*(build(uid) for uid in held), *(fresh(uid) for uid in waiting)]
    )
    limits = Limits(stacks=3, emergency=0, in_progress=9)

    found = occupied(store.all(), locks={f"spec/{uid}" for uid in held}, leases=(), now=START)
    started = started_by_round(inst, store, building=held)

    assert len(started) == free(found, limits, project=ProjectKey(repo="app"))
