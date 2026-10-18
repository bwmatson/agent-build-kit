"""A group is carried by at most one started unit that has not finished (spec:
a-started-unit-keeps-its-groups): `upsert` refuses a plan that gives such a unit's group to
another, and `StoredUnit.owns_groups` says who owns what."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import GroupOwned, UnitStore
from agent_build_kit.pipeline.units import PLANNED, Member, UnitState
from tests.factories import stored_unit


def store_with_owner(tmp_path: Path, *, groups: tuple[int, ...] = (16,)) -> UnitStore:
    """`app/3` of change `app` carrying `groups`, planned with a branch."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("app/3", change="app", groups=groups)])
    store.set_state("app/3", PLANNED, branch="spec/app/3")
    return store


def claiming_plan() -> list:
    """A plan that omits `app/3` and gives group 16 to a new `app/4`, beside `app/5`."""
    return [
        stored_unit("app/4", change="app", groups=(16,)),
        stored_unit("app/5", change="app", groups=(17,)),
    ]


def test_a_new_unit_may_not_take_the_group_of_a_started_planned_unit(tmp_path: Path) -> None:
    store = store_with_owner(tmp_path)
    before = store.path.read_bytes()

    with pytest.raises(GroupOwned) as refused:
        store.upsert(claiming_plan(), change="app")

    for name in ("app/3", "app/4", "16"):
        assert name in str(refused.value)
    assert store.path.read_bytes() == before, "nothing is written, the plan's other units too"
    assert "app/5" not in {unit.id for unit in store.all()}


@pytest.mark.parametrize("state", [UnitState.MERGED, UnitState.CLOSED, UnitState.SATISFIED])
def test_a_finished_owner_is_free(tmp_path: Path, state: UnitState) -> None:
    store = store_with_owner(tmp_path)
    store.set_state("app/3", state)

    store.upsert(claiming_plan(), change="app")

    assert store.get("app/4").groups == (16,)
    assert store.get("app/3").state == state
    assert not store.get("app/3").owns_groups


def test_an_unplanned_unit_without_work_is_free(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("app/3", change="app", groups=(16,))])
    store.upsert([], change="app")
    assert store.get("app/3").state == UnitState.UNPLANNED

    store.upsert(claiming_plan(), change="app")

    assert store.get("app/4").groups == (16,)
    assert not store.get("app/3").owns_groups


def test_an_unstarted_owner_is_reshaped_as_before(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("app/3", change="app", groups=(16,))])
    assert store.get("app/3").owns_groups, "it owns its group, but has not started"

    store.upsert(claiming_plan(), change="app")

    assert store.get("app/3").state == UnitState.UNPLANNED
    assert store.get("app/4").groups == (16,)


def test_a_group_carried_as_a_joined_member_counts(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            stored_unit(
                "platform/1",
                change="platform",
                groups=(1,),
                joined=(Member(change="app", groups=(16,)),),
            )
        ]
    )
    store.set_state("platform/1", PLANNED, branch="spec/platform/1")

    with pytest.raises(GroupOwned) as refused:
        store.upsert(claiming_plan(), change="app")

    assert "platform/1" in str(refused.value)


def test_two_unstarted_units_claiming_one_group_are_not_refused_here(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("app/3", change="app", groups=(16,))])

    store.upsert(
        [
            stored_unit("app/3", change="app", groups=(16,)),
            stored_unit("app/4", change="app", groups=(16,)),
        ],
        change="app",
    )

    assert store.get("app/3").owns_groups and store.get("app/4").owns_groups
    assert store.get("app/3").unstarted and store.get("app/4").unstarted


def test_a_plan_that_keeps_the_owner_with_its_group_and_moves_the_others_is_accepted(
    tmp_path: Path,
) -> None:
    store = store_with_owner(tmp_path, groups=(16, 17))

    store.upsert(
        [
            stored_unit("app/3", change="app", groups=(16,)),
            stored_unit("app/4", change="app", groups=(17,)),
        ],
        change="app",
    )

    assert store.get("app/3").groups == (16,)
    assert store.get("app/4").groups == (17,)
    assert store.get("app/3").owns_groups


def test_a_collision_already_in_the_store_is_not_refused(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            stored_unit("app/3", change="app", groups=(8,)),
            stored_unit("app/4", change="app", groups=(8,)),
        ]
    )
    store.set_state("app/3", PLANNED, branch="spec/app/3")
    plan = [
        stored_unit("app/3", change="app", groups=(8,)),
        stored_unit("app/4", change="app", groups=(8,)),
    ]

    store.upsert(plan, change="app")

    assert store.get("app/3").owns_groups and store.get("app/4").owns_groups
    assert store.get("app/3").branch == "spec/app/3"


def test_a_dropped_unit_the_plan_brings_back_is_a_new_claimant(tmp_path: Path) -> None:
    """`app/4` listed group 16 while it was `unplanned` with no work, which owns nothing, so
    planning it again is not a collision already stored."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("app/4", change="app", groups=(16,))], change="app")
    store.upsert([stored_unit("app/3", change="app", groups=(16,))], change="app")
    store.set_state("app/3", PLANNED, branch="spec/app/3")
    assert store.get("app/4").state == UnitState.UNPLANNED
    assert store.get("app/4").groups == (16,)
    before = store.path.read_bytes()

    with pytest.raises(GroupOwned) as refused:
        store.upsert([stored_unit("app/4", change="app", groups=(16,))], change="app")

    for name in ("app/3", "app/4", "16"):
        assert name in str(refused.value)
    assert store.path.read_bytes() == before


def test_an_unstarted_unit_that_listed_the_group_does_not_excuse_a_started_one_taking_it(
    tmp_path: Path,
) -> None:
    store = store_with_owner(tmp_path)
    store.upsert([stored_unit("app/4", change="app", groups=(17,))])

    with pytest.raises(GroupOwned) as refused:
        store.upsert(
            [
                stored_unit("app/3", change="app", groups=(16, 17)),
                stored_unit("app/4", change="app", groups=(17,)),
            ],
            change="app",
        )

    assert "app/3" in str(refused.value) and "app/4" in str(refused.value)


@pytest.mark.parametrize(
    ("state", "branch", "owns"),
    [
        (UnitState.PLANNED, "", True),
        (UnitState.RUNNING, "spec/app/3", True),
        (UnitState.IN_REVIEW, "spec/app/3", True),
        (UnitState.FAILED, "spec/app/3", True),
        (UnitState.HELD, "spec/app/3", True),
        (UnitState.UNPLANNED, "spec/app/3", True),
        (UnitState.UNPLANNED, "", False),
        (UnitState.MERGED, "spec/app/3", False),
        (UnitState.CLOSED, "spec/app/3", False),
        (UnitState.SATISFIED, "spec/app/3", False),
    ],
)
def test_which_states_own_their_groups(state: UnitState, branch: str, owns: bool) -> None:
    assert stored_unit("app/3", state=state, branch=branch).owns_groups is owns


@pytest.mark.parametrize(
    "work", [{"pr": 7}, {"pushed": "abc1234"}, {"approved": "abc1234"}], ids=lambda w: next(iter(w))
)
def test_an_unplanned_unit_owns_its_groups_by_any_kind_of_work(work: dict) -> None:
    assert stored_unit("app/3", state=UnitState.UNPLANNED, **work).owns_groups is True
