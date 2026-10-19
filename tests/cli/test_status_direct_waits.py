"""`abk status` names a waiting unit's direct dependencies, once each."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import HeldBy, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import FAILED, HELD, MERGED, PLANNED, direct_dependencies
from agent_build_kit.pipeline.vocabulary import WaitReason
from tests.cli.test_wait_reasons import workspace_with
from tests.conftest import status_lines
from tests.factories import new_unit

RECORDED = Path(__file__).parent.parent / "fixtures" / "stores" / "recorded_units.json"


def recording(units: list[StoredUnit]) -> Callable[[UnitStore], None]:
    """Put `units` in the store as they are, redundant dependencies and all (`upsert` would
    reduce them), each in its state and, if planned, with a branch so it has started."""

    def record(store: UnitStore) -> None:
        store.import_units(units)
        for unit in units:
            branch = f"spec/{unit.id}" if unit.state == PLANNED else unit.branch
            store.set_state(unit.id, unit.state, branch=branch, pr=unit.pr)

    return record


def chain(top_state: str = PLANNED) -> list[StoredUnit]:
    return [
        new_unit("base/1", state=FAILED),
        new_unit("mid/1", state=PLANNED, depends_on=("base/1",)),
        new_unit("top/1", state=top_state, depends_on=("base/1", "mid/1")),
    ]


def test_a_blocked_unit_with_a_redundant_ancestor_names_its_parent_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status_lines(tmp_path, monkeypatch, capsys, record=recording(chain()), limit=2)

    blocked = next(line for line in lines if "blocked: top/1" in line)
    assert blocked.endswith("waits on mid/1")


def test_a_failed_waiting_unit_names_its_parent_and_not_the_ancestor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status_lines(
        tmp_path, monkeypatch, capsys, record=recording(chain(top_state=FAILED)), limit=9
    )

    waiting = next(line for line in lines if "failed, waiting on" in line and "top/1" in line)
    assert "  failed, waiting on mid/1: top/1" in waiting


def test_a_unit_held_for_depth_names_its_direct_parents(tmp_path: Path) -> None:
    units = [
        new_unit("base/1", state=PLANNED),
        new_unit("mid/1", state=PLANNED, depends_on=("base/1",)),
        new_unit("top/1", state=PLANNED, depends_on=("base/1", "mid/1")),
    ]
    inst = workspace_with(tmp_path, {}, {})
    store = UnitStore(tmp_path / "units.json")
    store.import_units(units)
    store.set_state("top/1", HELD, note="stack too deep", held_by=HeldBy.DEPTH)

    waits = cli.wait_reasons(
        inst,
        store.all(),
        started=set(),
        building=set(),
        only=frozenset(),
        usage_paused=False,
    )

    assert waits["top/1"].reason is WaitReason.BLOCKED
    assert waits["top/1"].waits_on == ("mid/1",)


def test_the_status_of_a_recorded_store_names_only_direct_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    units = [
        unit if unit.state == MERGED else unit.model_copy(update={"state": PLANNED})
        for unit in UnitStore(RECORDED).all()
    ]
    direct = {unit.id: set(direct_dependencies(unit, units)) for unit in units}

    lines = status_lines(tmp_path, monkeypatch, capsys, record=recording(units), limit=20)

    blocked = [line for line in lines if "  blocked: " in line]
    assert any("feature/4" in line for line in blocked)
    for line in blocked:
        unit_id = line.split("blocked: ")[1].split(" ")[0]
        named = set(line.split("waits on ")[1].split(", "))
        flag = next(u for u in units if u.id == unit_id).flag
        if flag not in ("acceptance", "narrow"):
            assert named <= direct[unit_id], line
