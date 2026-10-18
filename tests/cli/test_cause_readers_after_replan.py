"""The readers of a unit's cause give the same answer after a demotion, a promotion and a replan.

Each reads the unit through the nearest public entry point; `replan` plans the same graph
again, or leaves the unit out and plans it again, as the store does on a replan.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.forges.transport import HostUnavailable
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, in_progress, ready_units
from tests.conftest import make_installation
from tests.factories import unit
from tests.runner_fakes import Recorder, make_runner
from tests.standing_causes import REPLANS, replan

pytestmark = pytest.mark.usefixtures("scripted_engine")

CHANGE = "add-marker"
UNIT = "add-marker/2"
PARENT = "add-marker/1"


def refused(*args: Any, **kwargs: Any) -> int:
    raise HostUnavailable("open pull request", "connection refused", 3)


@pytest.mark.parametrize("how", REPLANS)
def test_a_unit_sent_back_for_rework_is_gated_on_a_dependency_in_another_repo_after_a_replan(
    tmp_path: Path, how: str
) -> None:
    graph = [unit(PARENT, repo="platform"), unit(UNIT, depends_on=(PARENT,))]
    store = UnitStore(tmp_path / "units.json")
    store.upsert(graph, change=CHANGE)
    store.set_state(UNIT, PLANNED, branch=f"spec/{UNIT}", cause=Cause.REWORK)

    replan(store, how, graph, change=CHANGE)
    cli.gate_sent_back(store)

    assert store.get(UNIT).cause is Cause.GATED


@pytest.mark.parametrize("how", REPLANS)
def test_a_freshly_unblocked_unit_that_went_back_still_waits_for_room_after_a_replan(
    tmp_path: Path, how: str
) -> None:
    busy = [unit(f"busy/{n}", change="busy") for n in (1, 2)]
    graph = [unit(PARENT), unit(UNIT, depends_on=(PARENT,)), *busy]
    store = UnitStore(tmp_path / "units.json")
    store.upsert(graph, change=CHANGE)
    for stored in (PARENT, *(u.id for u in busy)):
        store.set_state(stored, IN_REVIEW, pr=1, branch=f"spec/{stored}")
    store.set_state(UNIT, PLANNED, branch=f"spec/{UNIT}", cause=Cause.UPSTREAM_WENT_BACK)

    def ready(limit: int) -> list[str]:
        return [
            u.id
            for u in ready_units(
                store.all(), max_concurrent=5, depth_cap=5, max_units_in_progress=limit
            )
        ]

    replan(store, how, graph, change=CHANGE)

    assert store.get(UNIT).cause is Cause.UPSTREAM_WENT_BACK
    assert ready(3) == [], "the three in review fill the limit"
    assert ready(4) == [UNIT]


@pytest.mark.parametrize("how", REPLANS)
def test_a_unit_parked_for_the_host_resumes_at_its_step_after_a_replan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    inst = make_installation(tmp_path, planning={"state_dir": "."})
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT)], change=CHANGE)

    def build_once(**overrides: Any) -> Recorder:
        recorder = Recorder(store)
        runner = make_runner(store, recorder, tmp_path, **overrides)
        monkeypatch.setattr(cli, "build_runner", lambda u, **kw: runner)
        assert cli.build_unit(inst, store.get(UNIT), store=store) is True
        return recorder

    build_once(open_pr=refused)
    assert store.get(UNIT).cause is Cause.HOST_UNAVAILABLE

    replan(store, how, [unit(UNIT)], change=CHANGE)
    recorder = build_once()

    for step in ("push", "unit-test", "e2e-test", "review"):
        assert step not in recorder.events
    assert store.get(UNIT).state == IN_REVIEW


@pytest.mark.parametrize("how", REPLANS)
def test_a_unit_parked_on_a_held_split_does_not_count_as_in_progress_after_a_replan(
    tmp_path: Path, how: str
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT)], change=CHANGE)
    store.set_state(UNIT, PLANNED, branch=f"spec/{UNIT}", cause=Cause.SPLIT_HELD)
    store.set_parked(UNIT, ("e2e-slow",))
    assert not in_progress(store.get(UNIT), store.all())

    replan(store, how, [unit(UNIT)], change=CHANGE)

    assert store.get(UNIT).cause is Cause.SPLIT_HELD
    assert not in_progress(store.get(UNIT), store.all())
