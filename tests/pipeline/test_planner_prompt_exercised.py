"""The acceptance rule of the planner prompt names the units the group exercises.

It used to ask for a dependency on every unit of the change, which put an edge from the
acceptance unit to units its chain already reaches. A unit that stores only the tail of its
chain and the independent units still waits for the rest (`earlier_units`).
"""

from __future__ import annotations

import re

from agent_build_kit.pipeline.planner import build_prompt
from tests.prompt_text import flat


def rule(opening: str, closing: str) -> str:
    text = flat(build_prompt({}, []))
    start = text.index(opening)
    return text[start : text.index(closing, start)]


def test_the_acceptance_rule_names_the_units_exercised_and_not_every_unit() -> None:
    acceptance = rule("The group flagged `[acceptance]`", "A group with an `Independent:")

    assert re.search(r"\bexercis", acceptance)
    assert "every unit" not in acceptance.lower()
    # The independent-group rule still puts the independent unit among its dependencies.
    independent = rule("A group with an `Independent:", "How the repos relate")
    assert (
        "An `[acceptance]` or `[narrow]` unit also depends on the independent unit" in independent
    )
    # The narrow rule is as it was.
    narrow = rule("The group flagged `[narrow]`", "The group flagged `[acceptance]`")
    assert "its unit depends on every unit that migrates a consumer" in narrow
    assert "nothing may depend on it" in narrow
