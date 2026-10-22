"""A superseded unit is closed, and the readers that differ for it treat it as finished without
merging, leave it closed under a plan, and show its pieces (spec: unit-superseding)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.archive import is_ready_to_archive
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import MERGED, UnitState, waiting_on
from tests.conftest import make_installation, run_status
from tests.factories import stored_unit, superseded_store, unit

OLD, FIRST, LAST = "app/3", "app/3-s1", "app/3-s2"


def test_a_change_whose_pieces_merged_is_ready_to_archive_without_the_superseded_unit_merging(
    tmp_path: Path,
) -> None:
    store = superseded_store(tmp_path)
    store.set_state("app/5", MERGED)

    assert not is_ready_to_archive("app", store.all()), "the pieces have not merged"

    store.set_state(FIRST, MERGED)
    store.set_state(LAST, MERGED)

    assert is_ready_to_archive("app", store.all())


def test_nothing_waits_on_a_superseded_unit_a_dependent_still_names(tmp_path: Path) -> None:
    store = superseded_store(tmp_path)
    store.import_units([stored_unit("app/6", change="app", groups=(6,), depends_on=(OLD,))])
    graph = store.all()

    waits = waiting_on(store.get("app/6"), graph)

    assert OLD not in [parent.id for parent in waits]


def test_a_plan_using_its_id_leaves_it_closed_with_its_cause_and_pieces(tmp_path: Path) -> None:
    store = superseded_store(tmp_path)

    store.upsert([unit(OLD, change="app", groups=(3, 4))], change="app")

    old = store.get(OLD)
    assert old.state == UnitState.CLOSED
    assert old.cause == Cause.SUPERSEDED
    assert old.superseded_by == (FIRST, LAST)


def test_status_shows_it_as_closed_with_its_pieces_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = make_installation(
        tmp_path, planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees"))
    )
    superseded_store(tmp_path)

    lines = run_status(inst, monkeypatch, capsys)

    [shown] = [line for line in lines if f"superseded: {OLD}" in line]
    assert f"by {FIRST}, {LAST}" in shown
