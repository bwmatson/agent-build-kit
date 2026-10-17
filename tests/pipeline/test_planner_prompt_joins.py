"""The joining paragraph of the planner prompt: related work first, then the more urgent
(spec: planner-priorities)."""

from __future__ import annotations

import re

from agent_build_kit.pipeline.planner import build_prompt
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
