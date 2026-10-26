"""The thread pool's admission (`run_round`) and the pure occupancy function agree on the same
fixtures: the units the round hands out are the free slots the function reports."""

import os
from pathlib import Path

import pytest

from agent_build_kit.pipeline.admission import admit
from agent_build_kit.pipeline.occupancy import Limits, free, occupied
from agent_build_kit.pipeline.units import ProjectKey
from tests.branch_lock_fakes import lock_held_by
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


def test_admission_and_the_round_both_start_a_project_s_fourth_unit_while_another_is_busy(
    tmp_path: Path,
) -> None:
    """Running units of one project do not count against another's: each project's own stacks
    are the only running limit, with no account to count them under."""
    inst = lane_workspace(tmp_path, workers=4, places=5, extra=0)
    held = [f"app{n}/1" for n in range(3)] + [f"plat{n}/1" for n in range(3)]
    store = seeded(
        inst,
        tmp_path,
        [
            *(build(uid, repo="app") for uid in held[:3]),
            *(build(uid, repo="platform") for uid in held[3:]),
            fresh("wait/1", repo="app"),
        ],
    )
    for uid in held:
        lock_held_by(inst, f"spec/{uid}", os.getpid())

    admitted = admit(inst, store, [store.get("wait/1")], worker="w1")

    assert [unit.id for unit in admitted] == ["wait/1"]
    assert started_by_round(inst, store, building=held) == ["wait/1"]
