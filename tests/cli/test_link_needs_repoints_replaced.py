"""`link_needs` rewrites a stored dependency on a replaced unit to its live successors, in any unit
that has not finished, started or not (spec: a-replaced-unit-points-to-its-successor)."""

from __future__ import annotations

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import UnitState, waiting_on
from tests.factories import stored_unit

NEEDS_X_3 = "# Tasks\n\n## 1. [app] [unit-test] G\n\nNeeds: x group 3 — why\n\n- [ ] 1.1 Do it\n"
NO_NEEDS = "# Tasks\n\n## 1. [app] [unit-test] G\n\n- [ ] 1.1 Do it\n"


def replaced(uid: str, *by: str, groups: tuple[int, ...] = (3,)) -> StoredUnit:
    return stored_unit(uid, change="x", groups=groups, state=UnitState.UNPLANNED, superseded_by=by)


def live(uid: str, groups: tuple[int, ...], **fields: object) -> StoredUnit:
    return stored_unit(uid, change="x", groups=groups, **fields)


def dependent(uid: str = "d/1", state: UnitState = UnitState.RUNNING) -> StoredUnit:
    return stored_unit(
        uid, change="d", groups=(1,), depends_on=("x/3",), state=state, branch=f"spec/{uid}"
    )


def tasks(inst: Installation, change: str, text: str) -> None:
    path = inst.changes_dir / change / "tasks.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def link(inst: Installation, *units: StoredUnit) -> UnitStore:
    store = UnitStore(inst.root / "units.json")
    store.import_units(units)
    cli.link_needs(inst, store=store)
    return store


def test_a_running_dependent_is_repointed_after_a_join_and_the_line_is_logged(
    installation: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    store = link(installation, replaced("x/3", "x/5"), live("x/5", (3, 4)), dependent())

    assert store.get("d/1").depends_on == ("x/5",)
    assert "d/1: dependency x/3 is now x/5 (replaced by a replan)" in capsys.readouterr().out


def test_a_planner_edge_on_a_split_unit_depends_on_both_successors(
    installation: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    store = link(
        installation,
        replaced("x/3", "x/4", "x/5", groups=(3, 4)),
        live("x/4", (3,)),
        live("x/5", (4,)),
        dependent("d/1", UnitState.PLANNED),
    )

    assert store.get("d/1").depends_on == ("x/4", "x/5")
    assert "dependency x/3 is now x/4, x/5 (replaced by a replan)" in capsys.readouterr().out


def test_a_needs_line_takes_only_the_successor_that_carries_its_group(
    installation: Installation,
) -> None:
    tasks(installation, "d", NEEDS_X_3)
    store = link(
        installation,
        replaced("x/3", "x/4", "x/5", groups=(3, 4)),
        live("x/4", (3,)),
        live("x/5", (4,)),
        dependent(),
    )

    assert store.get("d/1").depends_on == ("x/4",)
    assert store.get("d/1").needs == ("x/4",)

    tasks(installation, "d", NO_NEEDS)
    cli.link_needs(installation, store=store)

    assert store.get("d/1").needs == ()
    assert store.get("d/1").depends_on == ("x/4",)


def test_a_chain_is_followed_to_the_live_unit(installation: Installation) -> None:
    store = link(
        installation,
        replaced("x/3", "x/4"),
        replaced("x/4", "x/5"),
        live("x/5", (3,)),
        dependent(),
    )

    assert store.get("d/1").depends_on == ("x/5",)


def test_a_merged_successor_is_taken_and_the_wait_is_unchanged(installation: Installation) -> None:
    units = [replaced("x/3", "x/5"), live("x/5", (3,), state=UnitState.MERGED), dependent()]
    store = UnitStore(installation.root / "units.json")
    store.import_units(units)
    before = [u.id for u in waiting_on(store.get("d/1"), store.all())]

    cli.link_needs(installation, store=store)

    assert store.get("d/1").depends_on == ("x/5",)
    assert [u.id for u in waiting_on(store.get("d/1"), store.all())] == before == []


def test_a_successor_the_store_does_not_hold_stands_for_itself_and_changes_nothing(
    installation: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    store = link(installation, replaced("x/3", "x/9"), dependent())

    assert store.get("d/1").depends_on == ("x/3",)
    assert "is now" not in capsys.readouterr().out


def test_an_edge_with_no_successor_is_left_alone_beside_one_that_is_repointed(
    installation: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    both = dependent().model_copy(update={"depends_on": ("x/3", "y/3")})
    store = link(
        installation,
        replaced("x/3"),
        replaced("y/3", "y/5", groups=(7,)),
        live("y/5", (7,)),
        both,
    )

    assert store.get("d/1").depends_on == ("y/5",)
    out = capsys.readouterr().out
    assert "dependency y/3 is now y/5" in out
    assert "x/3 is now" not in out


def test_a_successor_that_closes_a_cycle_is_refused_once_and_the_old_edge_kept(
    installation: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    store = UnitStore(installation.root / "units.json")
    store.import_units(
        [replaced("x/3", "x/5"), live("x/5", (3,), depends_on=("d/1",)), dependent()]
    )
    reported: set[tuple[str, str]] = set()

    cli.link_needs(installation, store=store, reported=reported)
    cli.link_needs(installation, store=store, reported=reported)

    assert store.get("d/1").depends_on == ("x/3",)
    assert capsys.readouterr().out.count("d/1 -> x/5 -> d/1") == 1


def test_an_unstarted_planned_unit_is_repointed_too(installation: Installation) -> None:
    store = link(
        installation,
        replaced("x/3", "x/5"),
        live("x/5", (3,)),
        dependent("d/1", UnitState.PLANNED).model_copy(update={"branch": ""}),
    )

    assert store.get("d/1").depends_on == ("x/5",)


def test_a_second_run_changes_and_logs_nothing(
    installation: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    store = link(installation, replaced("x/3", "x/5"), live("x/5", (3,)), dependent())
    capsys.readouterr()
    before = store.path.read_text()

    cli.link_needs(installation, store=store)

    assert capsys.readouterr().out == ""
    assert store.path.read_text() == before
    assert store.get("d/1").depends_on == ("x/5",)


def test_a_unit_that_joined_the_replaced_one_drops_its_dependency_on_it(
    installation: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    store = link(
        installation,
        replaced("x/3", "x/1"),
        live("x/1", (1, 3), depends_on=("x/3",), state=UnitState.RUNNING, branch="spec/x/1"),
    )

    assert store.get("x/1").depends_on == ()
    assert "is now x/1" not in capsys.readouterr().out
