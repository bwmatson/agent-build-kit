"""What a unit parked for the code host holds (spec: git-host-outage, a building unit carries on and
a parked unit holds only its in-progress slot): it keeps its place among the units in progress, and
holds no worker, stack or unit-test slot, which only a run holds. Pinned here, not changed by the
marker."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline import occupancy
from agent_build_kit.pipeline.units import HELD, RUNNING, in_progress, project_key, start_room
from tests.code_host_fixtures import GITHUB, GITHUB_URL, give_remote, mark, park
from tests.fake_clock import FakeClock, install
from tests.tick_pass import Builder, install_builder, isolate, stored, warm_unit_graphs, workspace

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture(autouse=True)
def warmed(tmp_path: Path) -> None:
    warm_unit_graphs(tmp_path)


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate(monkeypatch)


@pytest.fixture
def builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Builder:
    return install_builder(tmp_path, monkeypatch)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    return install(monkeypatch)


def evaluated(inst, units):
    ready, view, *_ = cli._evaluate_round(
        inst, units, started=set(), building={"building/1"}, only=frozenset()
    )
    return ready, view


def test_a_parked_unit_keeps_its_in_progress_slot_while_its_marker_holds(
    tmp_path: Path, builder: Builder, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = workspace(tmp_path, in_progress=2)
    give_remote(inst, "app", GITHUB_URL)
    park(builder.store, "parked/1")
    builder.store.upsert([stored("new/1"), stored("building/1")])
    builder.store.set_state("building/1", RUNNING, branch="spec/building/1")
    mark(inst, GITHUB, repo="app", now=clock.now())

    ready, view = evaluated(inst, builder.store.all())

    parked = next(unit for unit in view if unit.id == "parked/1")
    assert in_progress(parked, view)
    assert start_room(view, 2, project_key(parked), project_key) == 0, "building/1 and parked/1"
    assert ready == [], "and new/1 is on the host that is down besides"


def test_a_parked_unit_holds_no_worker_or_place_that_a_run_holds(
    tmp_path: Path, builder: Builder, clock: FakeClock
) -> None:
    workspace(tmp_path)
    park(builder.store, "parked/1")
    builder.store.upsert([stored("building/1")])
    builder.store.set_state("building/1", RUNNING, branch="spec/building/1")
    units = builder.store.all()

    held = occupancy.occupied(
        units, locks=set(), leases=set(), now=datetime.now(UTC), held={"building/1"}
    )

    key = project_key(next(unit for unit in units if unit.id == "parked/1"))
    assert held.workers == {key: 1}, "the building unit's worker, and no other"
    assert held.projects == {key: 1}
    assert cli.slot_occupancy(units, {"building/1"}, set()) == {key: {"building/1"}}


def test_a_parked_unit_in_its_own_backoff_is_shown_held_and_frees_its_slot(
    tmp_path: Path, builder: Builder, clock: FakeClock
) -> None:
    """Existing behaviour for every parked cause, pinned: with no marker, a unit in its own
    backoff is held in the round's view, so it does not count as in progress there (the stored
    unit does)."""
    inst = workspace(tmp_path, in_progress=1)
    park(builder.store, "parked/1")
    builder.store.upsert([stored("new/1", repo="platform")])
    units = builder.store.all()

    ready, view, *_ = cli._evaluate_round(
        inst, units, started=set(), building=set(), only=frozenset()
    )

    parked = next(unit for unit in view if unit.id == "parked/1")
    assert parked.state == HELD
    assert not in_progress(parked, view)
    assert in_progress(next(u for u in units if u.id == "parked/1"), units)
    assert [unit.id for unit in ready] == ["new/1"]
