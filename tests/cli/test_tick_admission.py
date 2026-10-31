"""A pass hands units to workers through admission: each carries its worker's `starting` marker
until its build takes the branch lock, which then holds its place; a unit admission refuses is not
started."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.admission import STARTING_TTL, current_occupancy
from agent_build_kit.pipeline.unit_store import Starting, UnitStore
from agent_build_kit.pipeline.units import ProjectKey
from agent_build_kit.pipeline.workspaces import branch_held
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


@pytest.fixture(autouse=True)
def warmed(tmp_path: Path) -> None:
    warm_unit_graphs(tmp_path)


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate(monkeypatch)


@pytest.fixture
def builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Builder:
    return install_builder(tmp_path, monkeypatch)


def test_a_started_unit_carries_a_marker_before_its_build_and_none_once_the_lock_holds_it(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = workspace(tmp_path)
    builder.store.upsert([stored("feature/1")])
    real_build = cli.build_unit
    at_hand_over: dict[str, Starting | None] = {}
    under_lock: dict[str, Any] = {}

    def spy(inst: Any, unit: Any, **kwargs: Any) -> bool:
        at_hand_over[unit.id] = kwargs["store"].get(unit.id).starting
        return real_build(inst, unit, **kwargs)

    def inside_the_build() -> None:
        unit = builder.store.get("feature/1")
        under_lock["marker"] = unit.starting
        under_lock["held"] = branch_held("spec/feature/1", root=inst.locks_dir)
        under_lock["counted"] = current_occupancy(
            inst, builder.store.all(), datetime.now().astimezone()
        ).projects

    monkeypatch.setattr(cli, "build_unit", spy)
    builder.before_running["feature/1"] = inside_the_build

    assert tick(inst) == 0

    marker = at_hand_over["feature/1"]
    assert marker is not None
    assert marker.worker.startswith("tick-")
    assert marker.until - STARTING_TTL <= datetime.now(marker.until.tzinfo)
    assert under_lock["marker"] is None
    assert under_lock["held"] is True
    assert under_lock["counted"] == {ProjectKey(repo="app"): 1}
    assert builder.store.get("feature/1").starting is None


def test_a_unit_whose_build_ends_without_taking_the_lock_leaves_no_marker(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = workspace(tmp_path)
    builder.store.upsert([stored("feature/1")])

    def never_locks(inst: Any, unit: Any, **kwargs: Any) -> bool:
        return True

    monkeypatch.setattr(cli, "build_unit", never_locks)

    assert tick(inst) == 0

    assert builder.store.get("feature/1").starting is None


def test_a_unit_admission_refuses_is_not_started(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = workspace(tmp_path)
    builder.store.upsert([stored("feature/1")])
    monkeypatch.setattr(cli, "admit", lambda *args, **kwargs: [])

    assert tick(inst) == 0

    assert builder.started == []
    assert UnitStore(tmp_path / "units.json").get("feature/1").starting is None
