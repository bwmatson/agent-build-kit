"""A pull request body names the unmerged direct parents, and each parent's own body the rest."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.pr_body import assumptions, stack_line
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import direct_dependencies
from tests.factories import stored_unit as unit

RECORDED = Path(__file__).parent.parent / "fixtures" / "stores" / "recorded_units.json"


def chain() -> list[StoredUnit]:
    return [
        unit("a/1", change="a", state="in_review", pr=1),
        unit("a/2", change="a", state="in_review", pr=2, depends_on=("a/1",)),
        unit("a/3", change="a", depends_on=("a/1", "a/2")),
    ]


def test_the_merge_first_line_names_the_unmerged_direct_parent_with_its_number() -> None:
    graph = chain()

    line = stack_line(graph[2], graph, base="spec/a/2")

    assert "**Merge `a/2` (#2) first**" in line
    assert "`a/1`" not in line


def test_a_grandparent_is_named_by_the_parents_own_body_and_not_the_childs() -> None:
    graph = chain()

    child = stack_line(graph[2], graph, base="spec/a/2")
    parent = stack_line(graph[1], graph, base="spec/a/1")

    assert "`a/1`" not in child
    assert "**Merge `a/1` (#1) first**" in parent


def test_a_unit_whose_direct_parent_has_merged_says_it_is_ready() -> None:
    graph = [
        unit("a/1", change="a", state="in_review", pr=1),
        unit("a/2", change="a", state="merged", pr=2, depends_on=("a/1",)),
        unit("a/3", change="a", depends_on=("a/1", "a/2")),
    ]

    line = stack_line(graph[2], graph, base="main")

    assert "ready to merge" in line
    assert "Merge" not in line


def test_the_assumptions_list_the_same_parents() -> None:
    graph = chain()

    text = assumptions(graph[2], graph)

    assert "`a/2`" in text
    assert "`a/1`" not in text


def test_the_body_of_every_recorded_unit_names_only_direct_parents() -> None:
    units = [u.model_copy(update={"state": "in_review"}) for u in UnitStore(RECORDED).all()]

    for u in units:
        direct = set(direct_dependencies(u, units))
        named = {
            token.strip("`")
            for token in stack_line(u, units, base="main").split()
            if token.startswith("`") and token.endswith("`") and "/" in token
        }
        assert named <= direct, u.id
    third = next(u for u in units if u.id == "feature/3")
    assert "`feature/1`" not in stack_line(third, units, base="main")
    assert "`feature/2`" in stack_line(third, units, base="main")
