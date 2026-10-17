"""The joining paragraph of the planner prompt: related work first, then the more urgent
(spec: planner-priorities)."""

from __future__ import annotations

import re

import pytest

from agent_build_kit.pipeline.joins import JoinContext, JoinRefused, check_joins
from agent_build_kit.pipeline.planner import build_prompt
from agent_build_kit.pipeline.units import Join
from agent_build_kit.pipeline.work_graph import TaskGroup
from tests.factories import stored_unit
from tests.prompt_text import flat


def joining() -> str:
    text = flat(build_prompt({}, []))
    return text[text.index("Joining:") : text.index("Respond with exactly")]


def test_the_paragraph_joins_work_that_belongs_together_before_anything_else() -> None:
    text = joining().lower()

    assert re.search(r"groups of one change[^.]*groups of different changes", text)
    assert re.search(r"same or closely related files or modules", text)


def test_among_equal_fits_the_more_urgent_work_is_joined_first() -> None:
    text = joining().lower()

    assert re.search(r"fit[^.]*equally[^.]*more urgent[^.]*first", text)
    assert re.search(r"less urgent[^.]*partner[^.]*more urgent", text)


def test_a_priority_never_overrides_a_better_fit_or_joins_unrelated_work() -> None:
    text = joining().lower()

    assert re.search(r"priority never overrides a better fit", text)
    assert re.search(r"never joins? unrelated work", text)
    assert re.search(r"most urgent priority of its groups", text)


def test_the_paragraph_states_no_priority_number_limit() -> None:
    text = joining().lower()

    assert "most urgent priority of its groups" in text
    assert not re.search(r"priority (number )?(limit|above|below)\b|priorities? [0-5]\b", text)


def test_the_paragraph_keeps_the_rule_against_joining_two_units_because_both_are_small() -> None:
    assert "merely because both are small" in joining()


def group_at(priority: int) -> TaskGroup:
    return TaskGroup(
        number=1, repo="app", tier="unit-test", title="A", line=3, task_count=2, priority=priority
    )


def join_of(*, lines: int = 100, started: bool = False) -> None:
    """A priority-1 group joined onto a priority-5 unit."""
    onto = stored_unit("base/1", change="base", groups=(1,), priority=5)
    if started:
        onto = onto.model_copy(update={"branch": "spec/base/1"})
    check_joins(
        [Join(onto="base/1", change="feature", groups=(1,), estimated_lines=lines)],
        context=JoinContext(stored=(onto,), catalog={"base": (group_at(5),)}),
        plan=[],
        change="feature",
        groups=[group_at(1)],
        built=set(),
        ceiling=750,
    )


def test_a_join_across_priorities_that_meets_every_rule_is_accepted() -> None:
    join_of()


@pytest.mark.parametrize(
    ("broken", "rule"),
    [({"lines": 800}, "ceiling"), ({"started": True}, "has started")],
)
def test_a_join_across_priorities_that_breaks_a_rule_is_refused_for_that_rule_alone(
    broken: dict, rule: str
) -> None:
    with pytest.raises(JoinRefused, match=rule) as refused:
        join_of(**broken)

    assert "priorit" not in str(refused.value).lower()
