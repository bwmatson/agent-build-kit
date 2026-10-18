"""`link_needs` drops a stored dependency on a unit that builds nothing and no line declares.

A replan can move a group to another unit and unplan the first; a started unit keeps its
edge to it. Nothing waits on a unit that builds nothing, so dropping the edge changes no wait.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import (
    FAILED,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    UnitState,
    waiting_on,
)
from tests.cli.replan_driver import Replan, needs_md, tasks_md
from tests.factories import unit


def stale(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, parent_state: UnitState) -> Replan:
    """`a/2` is running with a stored dependency on `a/1`, which is now `parent_state`."""
    run = Replan(tmp_path, monkeypatch, a=tasks_md(2))
    run.store.upsert(
        [
            unit("a/1", change="a", groups=(1,)),
            unit("a/2", change="a", groups=(2,), depends_on=("a/1",)),
        ]
    )
    run.store.set_state("a/1", parent_state, branch="spec/a/1", pr=1)
    run.store.set_state("a/2", RUNNING, branch="spec/a/2")
    return run


def add_stale_sibling(run: Replan) -> None:
    """`a/3` is running on `gone/1`, which is unplanned: the edge each test below must still
    see dropped, beside whatever it keeps."""
    run.store.upsert(
        [
            unit("gone/1", change="gone", groups=(1,)),
            unit("a/3", change="a", groups=(3,), depends_on=("gone/1",)),
        ]
    )
    run.store.set_state("gone/1", UnitState.UNPLANNED)
    run.store.set_state("a/3", RUNNING, branch="spec/a/3")


def dropped_lines(capsys: pytest.CaptureFixture[str]) -> list[str]:
    return [line for line in capsys.readouterr().out.splitlines() if "dropped dependency" in line]


@pytest.mark.parametrize("state", [UnitState.UNPLANNED, UnitState.RETIRED])
def test_a_stale_edge_to_a_unit_that_builds_nothing_is_dropped_and_logged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    state: UnitState,
) -> None:
    run = stale(tmp_path, monkeypatch, state)

    cli.link_needs(run.inst, store=run.store)

    assert run.store.get("a/2").depends_on == ()
    lines = dropped_lines(capsys)
    assert len(lines) == 1
    assert "a/2: dropped dependency a/1: it builds nothing" in lines[0]


def test_a_second_run_drops_and_logs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = stale(tmp_path, monkeypatch, UnitState.UNPLANNED)
    cli.link_needs(run.inst, store=run.store)
    capsys.readouterr()

    cli.link_needs(run.inst, store=run.store)

    assert run.store.get("a/2").depends_on == ()
    assert dropped_lines(capsys) == []


def test_a_stale_edge_on_a_unit_with_no_needs_line_is_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = stale(tmp_path, monkeypatch, UnitState.UNPLANNED)
    assert run.store.get("a/2").needs == ()

    cli.link_needs(run.inst, store=run.store)

    assert run.store.get("a/2").depends_on == ()


@pytest.mark.parametrize("state", [PLANNED, IN_REVIEW, MERGED, FAILED])
def test_an_edge_to_a_unit_still_to_be_built_or_built_is_kept(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    state: UnitState,
) -> None:
    run = stale(tmp_path, monkeypatch, state)
    add_stale_sibling(run)

    cli.link_needs(run.inst, store=run.store)

    assert run.store.get("a/2").depends_on == ("a/1",)
    assert run.store.get("a/3").depends_on == ()
    assert len(dropped_lines(capsys)) == 1


def test_a_declared_edge_stays_and_the_stale_edge_beside_it_is_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = Replan(tmp_path, monkeypatch, old=tasks_md(1), a=tasks_md(1), b=needs_md("a group 1"))
    run.store.upsert(
        [
            unit("old/1", change="old", groups=(1,)),
            unit("a/1", change="a", groups=(1,)),
            unit("b/1", change="b", groups=(1,), depends_on=("old/1",)),
        ]
    )
    run.store.set_state("old/1", UnitState.UNPLANNED)
    run.store.set_state("b/1", RUNNING, branch="spec/b/1")

    cli.link_needs(run.inst, store=run.store)

    assert run.store.get("b/1").depends_on == ("a/1",)
    assert run.store.get("b/1").needs == ("a/1",)


def test_an_edge_to_an_id_not_in_the_store_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = Replan(tmp_path, monkeypatch, a=tasks_md(1))
    run.store.upsert([unit("a/1", change="a", groups=(1,), depends_on=("ghost/1",))])
    run.store.set_state("a/1", RUNNING, branch="spec/a/1")
    add_stale_sibling(run)

    cli.link_needs(run.inst, store=run.store)

    assert run.store.get("a/1").depends_on == ("ghost/1",)
    assert run.store.get("a/3").depends_on == ()


@pytest.mark.parametrize("own", [MERGED, UnitState.UNPLANNED])
def test_a_merged_unit_and_an_unplanned_unit_are_left_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, own: UnitState
) -> None:
    run = stale(tmp_path, monkeypatch, UnitState.UNPLANNED)
    run.store.set_state("a/2", own, branch="spec/a/2", pr=2)
    add_stale_sibling(run)

    cli.link_needs(run.inst, store=run.store)

    assert run.store.get("a/2").depends_on == ("a/1",)
    assert run.store.get("a/3").depends_on == ()


def test_dropping_the_edge_changes_no_wait(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = stale(tmp_path, monkeypatch, UnitState.UNPLANNED)
    run.store.set_state("a/2", PLANNED)
    before = [u.id for u in waiting_on(run.store.get("a/2"), run.store.all())]

    cli.link_needs(run.inst, store=run.store)

    assert run.store.get("a/2").depends_on == ()
    after = [u.id for u in waiting_on(run.store.get("a/2"), run.store.all())]
    assert before == after == []
