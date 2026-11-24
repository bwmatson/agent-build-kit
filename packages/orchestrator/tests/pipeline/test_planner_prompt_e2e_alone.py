"""The planner prompt says an `[e2e-test]` group is a unit of its own (spec: unit-joining,
unit-sizing)."""

from __future__ import annotations

from agent_build_kit.pipeline.planner import build_prompt
from tests.prompt_text import flat


def between(start: str, end: str) -> str:
    text = flat(build_prompt({}, []))
    return text[text.index(start) : text.index(end)]


def test_the_grouping_rule_makes_an_e2e_group_a_unit_of_its_own_whatever_its_size() -> None:
    grouping = between("Group consecutive task groups", "Never combine groups")

    assert "[e2e-test]" in grouping
    assert "unit of its own" in grouping
    assert "however small" in grouping


def test_an_e2e_group_flagged_or_not_stands_alone_and_follows_the_chain() -> None:
    stand_alone = between("`[e2e-test]` group, flagged or not", "How the repos relate")

    assert "never combined with another group" in stand_alone


def test_the_join_rules_no_longer_pair_e2e_with_e2e() -> None:
    text = flat(build_prompt({}, []))
    rules = between("Every join must satisfy", "A unit joined to may be joined to again")

    assert "`e2e-test` only with `e2e-test`" not in text
    assert "never joined, not even with another `e2e-test` unit" in rules


def test_the_join_rules_list_e2e_among_the_groups_no_join_involves() -> None:
    rules = between("no group involved is", "the two estimates together")

    assert "`[e2e-test]`" in rules
