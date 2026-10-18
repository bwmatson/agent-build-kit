"""`parse_plan` reads a unit's id as a label and has the program assign the id from the groups
(spec: unit-ids-come-from-the-groups)."""

from __future__ import annotations

import json

import pytest

from agent_build_kit.pipeline.joins import JoinContext
from agent_build_kit.pipeline.planner import PlannerError, parse_graph, parse_plan
from agent_build_kit.pipeline.units import RUNNING, UnitState
from tests.factories import groups_at, stored_unit


def planned(label: str, groups: tuple[int, ...], **extra) -> dict:
    return {
        "id": label,
        "change": "x",
        "title": "A unit",
        "repo": "app",
        "tier": "unit-test",
        "depends_on": [],
        "estimated_lines": 80,
        "groups": list(groups),
        **extra,
    }


def reply(*units: dict, joins: list[dict] | None = None) -> str:
    return json.dumps({"units": list(units), "joins": joins or []})


def read(text: str, *, count: int, stored=(), retired=(), built=()):
    return parse_plan(
        text,
        groups=groups_at(*([3] * count)),
        change="x",
        context=JoinContext(stored=tuple(stored), catalog={}),
        retired=set(retired),
        built=set(built),
        known={s.id for s in stored},
    )


def test_labels_become_ids_from_the_groups_and_the_dependency_follows() -> None:
    text = reply(planned("u1", (1,)), planned("u2", (2, 3), depends_on=["u1"]))

    plan = read(text, count=3)

    assert [u.id for u in plan.units] == ["x/1", "x/2"]
    assert plan.units[1].depends_on == ("x/1",)


def test_the_old_form_is_accepted_as_labels() -> None:
    text = reply(planned("x/7", (3,)), planned("x/9", (4,), depends_on=["x/7"]))

    plan = read(text, count=4, built={1, 2})

    assert [u.id for u in plan.units] == ["x/3", "x/4"]
    assert plan.units[1].depends_on == ("x/3",)


def test_a_dependency_on_a_stored_unit_that_is_no_label_is_left() -> None:
    merged = stored_unit("x/1", change="x", groups=(1,), state=UnitState.MERGED)
    text = reply(planned("u2", (2,), depends_on=["x/1"]))

    plan = read(text, count=2, stored=[merged], built={1})

    assert plan.units[0].id == "x/2"
    assert plan.units[0].depends_on == ("x/1",)


def test_an_excuse_keyed_by_label_is_accepted_and_one_for_a_non_dependency_is_refused() -> None:
    groups = groups_at(2, 4)
    context = JoinContext(stored=(), catalog={})
    urgent = planned("u1", (1,), depends_on=["u2"], needs_less_urgent={"u2": "it needs the helper"})
    text = reply(urgent, planned("u2", (2,)))

    plan = parse_plan(text, groups=groups, change="x", context=context)

    assert [u.id for u in plan.units] == ["x/1", "x/2"]
    assert plan.units[0].depends_on == ("x/2",)
    bad = reply(planned("u1", (1,), needs_less_urgent={"u2": "why"}), planned("u2", (2,)))
    with pytest.raises(PlannerError, match="u2"):
        parse_plan(bad, groups=groups, change="x", context=context)


def test_a_duplicate_label_is_refused_naming_it() -> None:
    assert [u.id for u in read(reply(planned("u1", (1,)), planned("u2", (2,))), count=2).units] == [
        "x/1",
        "x/2",
    ]

    with pytest.raises(PlannerError, match="u1"):
        read(reply(planned("u1", (1,)), planned("u1", (2,))), count=2)


def test_a_label_that_is_a_retired_id_is_refused_naming_it() -> None:
    retired = stored_unit("x/3", change="x", groups=(3,), state=UnitState.RETIRED, branch="b")
    kept = {"stored": [retired], "retired": {"x/3"}}

    built = {1, 2, 4, 5}
    plan = read(reply(planned("u1", (3,))), count=5, built=built, **kept)

    assert [u.id for u in plan.units] == ["x/6"]
    with pytest.raises(PlannerError, match=r"x/3"):
        read(reply(planned("x/3", (3,))), count=5, built=built, **kept)


def test_a_label_that_is_a_running_units_id_is_refused_naming_it() -> None:
    running = stored_unit("x/2", change="x", groups=(2,), state=RUNNING, branch="spec/x/2")
    text = reply(planned("x/2", (1,)))

    with pytest.raises(PlannerError, match=r"x/2"):
        read(text, count=2, stored=[running])


def test_a_label_that_is_an_unstarted_units_id_is_accepted() -> None:
    unstarted = stored_unit("x/9", change="x", groups=(2,))
    text = reply(planned("x/9", (1,)), planned("u2", (2,)))

    plan = read(text, count=2, stored=[unstarted])

    assert [u.id for u in plan.units] == ["x/1", "x/9"], "the match is owed the id, not the label"


def test_joins_are_returned_unchanged() -> None:
    onto = stored_unit("y/1", change="y", groups=(1,))
    later = stored_unit("z/1", change="z", groups=(1,), depends_on=("y/1",))
    catalog = {"y": tuple(groups_at(3)), "z": tuple(groups_at(3))}
    context = JoinContext(stored=(onto, later), catalog=catalog)

    plan = parse_plan(
        reply(planned("u1", (1,)), joins=[{"onto": "y/1", "unit": "z/1"}]),
        groups=groups_at(3),
        change="x",
        context=context,
        known={"y/1", "z/1"},
    )

    assert [u.id for u in plan.units] == ["x/1"]
    assert [(j.onto, j.unit) for j in plan.joins] == [("y/1", "z/1")]


def test_a_refusal_holds_the_labels() -> None:
    text = reply(planned("u1", (1,)), planned("u2", (9,)))

    with pytest.raises(PlannerError) as refused:
        read(text, count=2)

    assert refused.value.units == ("u1", "u2")
    assert [u.id for u in read(reply(planned("u1", (1,)), planned("u2", (2,))), count=2).units] == [
        "x/1",
        "x/2",
    ]


def test_parse_graph_with_no_context_assigns_ids_from_the_groups() -> None:
    units = parse_graph(
        reply(planned("u1", (2,)), planned("u2", (1,))), groups=groups_at(3, 3), known=set()
    )

    assert [u.id for u in units] == ["x/2", "x/1"]
