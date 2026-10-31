"""A unit's group modes in the store: kept once started, defaulted when absent, carried by a
join and a supersede (spec: group-build-modes)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.unit_store import HeldBy, UnitStore
from agent_build_kit.pipeline.units import HELD, RUNNING, Join, UnitState
from agent_build_kit.pipeline.work_graph import GroupMode
from tests.factories import groups_at, stored_unit, unit

ID = "add-marker/1"


def test_a_replan_gives_an_unstarted_unit_new_modes_and_a_started_one_keeps_its_own(
    tmp_path: Path,
) -> None:
    store = UnitStore(tmp_path / "units.json")
    first, second = {"add-marker/1": "no_code"}, {"add-marker/2": "no_code"}
    store.upsert([unit(ID, group_modes=first), unit("add-marker/2", group_modes=second)])
    store.set_state(ID, RUNNING)
    changed = {"add-marker/1": "tests_and_code"}

    store.upsert(
        [unit(ID, group_modes=changed), unit("add-marker/2", group_modes=changed)],
        change="add-marker",
    )

    assert store.get(ID).group_modes == first
    assert store.get("add-marker/2").group_modes == changed


def test_a_unit_with_no_stored_value_takes_tests_only_for_e2e_and_tests_and_code_otherwise() -> (
    None
):
    e2e, plain = groups_at(3, 3)
    e2e = e2e.model_copy(update={"tier": TestTier.E2E_TEST})
    held = unit(ID, group_modes={})

    assert held.mode_of("add-marker", e2e) is GroupMode.TESTS_ONLY
    assert held.mode_of("add-marker", plain) is GroupMode.TESTS_AND_CODE


def test_a_stored_value_is_the_mode_of_its_group() -> None:
    plain = groups_at(3)[0]
    held = unit(ID, group_modes={"add-marker/1": "no_code"})

    assert held.mode_of("add-marker", plain) is GroupMode.NO_CODE


def test_a_join_carries_the_modes_of_the_unit_joined_in(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            unit(ID, group_modes={"add-marker/1": "no_code"}),
            unit("other/1", change="other", group_modes={"other/1": "tests_and_code"}),
        ]
    )

    assert store.join(Join(onto=ID, unit="other/1"), group_kinds=[]) is not None

    assert store.get(ID).group_modes == {
        "add-marker/1": "no_code",
        "other/1": "tests_and_code",
    }


def test_a_supersede_gives_each_piece_the_modes_of_the_groups_it_holds(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.import_units(
        [
            stored_unit(
                "app/3",
                change="app",
                groups=(3, 4),
                group_modes={"app/3": "no_code", "app/4": "tests_and_code"},
            )
        ]
    )
    store.set_state("app/3", HELD, held_by=HeldBy.SIZE)
    # A piece arrives with the floor the planner filled in, which may differ from the held value.
    pieces = [
        unit("app/3-s1", change="app", groups=(3,), group_modes={"app/3": "tests_and_code"}),
        unit("app/3-s2", change="app", groups=(4,), group_modes={"app/4": "tests_and_code"}),
    ]

    store.supersede("app/3", pieces)

    assert store.get("app/3-s1").group_modes == {"app/3": "no_code"}
    assert store.get("app/3-s2").group_modes == {"app/4": "tests_and_code"}
    assert store.get("app/3").state is UnitState.CLOSED


def test_a_join_of_a_changes_groups_stores_the_modes_the_join_carries(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(ID, group_modes={"add-marker/1": "tests_and_code"})])
    join = Join(onto=ID, change="other", groups=(1,), group_modes={"other/1": "no_code"})

    assert store.join(join, group_kinds=[]) is not None

    assert store.get(ID).group_modes == {
        "add-marker/1": "tests_and_code",
        "other/1": "no_code",
    }


def test_a_replan_of_an_unstarted_unit_keeps_the_modes_of_the_groups_it_carries(
    tmp_path: Path,
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(ID, group_modes={"add-marker/1": "tests_and_code"})])
    join = Join(onto=ID, change="other", groups=(1,), group_modes={"other/1": "no_code"})
    assert store.join(join, group_kinds=[]) is not None

    store.upsert([unit(ID, group_modes={"add-marker/1": "no_code"})], change="add-marker")

    assert store.get(ID).group_modes == {"add-marker/1": "no_code", "other/1": "no_code"}
