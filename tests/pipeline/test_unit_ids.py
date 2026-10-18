"""The program names a planned unit from the groups it carries (unit-ids-come-from-the-groups)."""

from __future__ import annotations

from collections.abc import Sequence

from agent_build_kit.pipeline.unit_ids import assign_unit_ids
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import MERGED, RUNNING, Member, UnitState, unit_number
from tests.factories import stored_unit, unit

CHANGE = "x"


def labelled(label: str, groups: tuple[int, ...], **overrides):
    return unit(label, change=CHANGE, groups=groups, **overrides)


def assigned(
    units, stored: Sequence[StoredUnit] = (), *, retired=(), highest: int = 5
) -> list[str]:
    result = assign_unit_ids(
        units, stored=list(stored), retired=set(retired), highest_group=highest
    )
    return [u.id for u in result]


def held(uid: str, groups: tuple[int, ...], state: UnitState = RUNNING) -> StoredUnit:
    return stored_unit(uid, change=CHANGE, groups=groups, state=state, branch=f"spec/{uid}")


def test_the_id_is_the_change_and_the_lowest_own_group() -> None:
    units = [labelled("u1", (1, 2)), labelled("u2", (3,)), labelled("u3", (4, 5))]

    assert assigned(units) == ["x/1", "x/3", "x/4"]


def test_the_lowest_group_is_the_lowest_even_when_listed_later() -> None:
    assert assigned([labelled("u1", (4, 2)), labelled("u2", (1,))], highest=4) == ["x/2", "x/1"]


def test_a_group_of_another_change_carried_by_a_join_does_not_count() -> None:
    joined = labelled("u1", (5,)).model_copy(update={"joined": (Member(change="y", groups=(2,)),)})

    assert assigned([joined]) == ["x/5"]


def test_other_labels_and_the_same_groups_give_the_same_ids() -> None:
    first = assigned([labelled("u1", (1, 2)), labelled("u2", (3,))])
    second = assigned([labelled("a", (1, 2)), labelled("b", (3,))])

    assert first == second == ["x/1", "x/3"]


def test_a_unit_with_no_group_of_its_change_keeps_its_label() -> None:
    assert assigned([labelled("u1", ()), labelled("u2", (2,))]) == ["u1", "x/2"]


def test_a_stored_unplanned_unit_with_no_work_is_reused_for_the_same_groups() -> None:
    stored = [stored_unit("x/4", change=CHANGE, groups=(3, 4), state=UnitState.UNPLANNED)]

    assert assigned([labelled("u1", (3, 4))], stored) == ["x/4"]


def test_an_unstarted_unit_with_the_same_groups_keeps_its_id_whatever_the_number() -> None:
    stored = [stored_unit("x/4", change=CHANGE, groups=(3, 4))]

    assert assigned([labelled("u1", (3, 4))], stored) == ["x/4"]


def test_a_match_is_owed_its_id_before_the_rule_gives_it_away() -> None:
    stored = [stored_unit("x/2", change=CHANGE, groups=(3, 4))]

    ids = assigned([labelled("u1", (2,)), labelled("u2", (3, 4))], stored)

    assert ids[1] == "x/2"
    assert ids[0] != "x/2"
    assert ids[0].rsplit("/", 1)[1].isdigit()


def test_two_calls_over_the_stored_result_of_the_first_give_the_same_ids() -> None:
    units = [labelled("u1", (1, 2)), labelled("u2", (3,)), labelled("u3", (4, 5))]
    first = assign_unit_ids(units, stored=[], retired=set(), highest_group=5)
    stored = [stored_unit(u.id, change=CHANGE, groups=u.groups) for u in first]

    again = assigned([labelled("a", (1, 2)), labelled("b", (3,)), labelled("c", (4, 5))], stored)

    assert again == [u.id for u in first] == ["x/1", "x/3", "x/4"]


def test_a_split_of_an_unstarted_unit_leaves_its_id_on_the_lowest_group() -> None:
    stored = [stored_unit("x/3", change=CHANGE, groups=(3, 4))]

    assert assigned([labelled("u1", (3,)), labelled("u2", (4,))], stored) == ["x/3", "x/4"]


def test_a_retired_id_is_skipped_for_the_integer_after_the_highest_group() -> None:
    retired = held("x/3", (3,), state=UnitState.RETIRED)

    assert assigned([labelled("u1", (3,))], [retired], retired={"x/3"}) == ["x/6"]


def test_a_running_unit_is_never_given_away() -> None:
    stored = [held("x/2", (3, 4)), held("x/7", (1,), state=MERGED)]

    ids = assigned([labelled("u1", (2,))], stored, highest=4)

    assert ids[0] not in {"x/2", "x/7"}
    assert unit_number(unit(ids[0])) > 7


def test_a_merged_unit_holds_its_id_and_the_fallback_is_a_number_unit_number_reads() -> None:
    ids = assigned([labelled("u1", (3,))], [held("x/3", (3,), state=MERGED)])

    assert ids == ["x/6"]
    assert unit_number(unit(ids[0])) == 6


def test_an_unstarted_unit_with_other_groups_is_reused_in_place() -> None:
    stored = [stored_unit("x/3", change=CHANGE, groups=(3, 4))]

    assert assigned([labelled("u1", (3,))], stored) == ["x/3"]


def test_a_split_suffixed_stored_id_counts_as_its_leading_number() -> None:
    stored = [held("x/3", (3,), state=MERGED), held("x/8-s1", (8,), state=MERGED)]

    assert assigned([labelled("u1", (3,))], stored, highest=5) == ["x/9"]


def test_a_started_units_record_is_not_touched() -> None:
    running = held("x/2", (3, 4))
    before = running.model_copy()

    assigned([labelled("u1", (2,))], [running], highest=4)

    assert running == before


def test_dependencies_on_labels_become_ids_and_a_stored_dependency_is_left() -> None:
    units = [
        labelled("u1", (1,)),
        labelled("u2", (2,), depends_on=("u1", "x/9", "u1")),
    ]

    result = assign_unit_ids(units, stored=[], retired=set(), highest_group=2)

    assert result[1].depends_on == ("x/1", "x/9")
