"""The planner is told which groups are taken: the rule, and a marker on each taken heading."""

from __future__ import annotations

import re

from agent_build_kit.pipeline.planner import build_prompt, in_flight_item
from agent_build_kit.pipeline.units import FAILED
from tests.factories import stored_unit

TASKS = (
    "# Tasks\n\n"
    "## 1. [app] [tier1] Group one\n\n- [ ] 1.1 Test: it.\n\n"
    "## 2. [app] [tier1] Group two\n\n- [ ] 2.1 Test: it.\n"
)
CHANGES = {"feature": TASKS}
RULE = re.compile(r"(?i)built[^.]*\bnever\b[^.]*claim|\bnever\b[^.]*claim[^.]*built")


def taken() -> list[dict]:
    unit = stored_unit("feature/1", change="feature", groups=(1,), state=FAILED)
    return [in_flight_item(unit)]


def test_the_prompt_states_that_built_groups_are_never_claimed() -> None:
    assert RULE.search(build_prompt(CHANGES, taken()))


def test_only_the_heading_of_a_group_a_started_unit_builds_is_marked() -> None:
    prompt = build_prompt(CHANGES, taken())

    headings = [line for line in prompt.splitlines() if line.startswith("## ")]
    assert [line for line in headings if "(built by" in line] == [
        "## 1. [app] [tier1] Group one (built by feature/1)"
    ]
    assert "## 2. [app] [tier1] Group two" in headings


def test_a_heading_the_validator_reads_with_extra_whitespace_is_marked_too() -> None:
    tasks = TASKS.replace("## 2. [app]", "##  2. [app]")
    unit = stored_unit("feature/2", change="feature", groups=(2,), state=FAILED)

    prompt = build_prompt({"feature": tasks}, [in_flight_item(unit)])

    assert "##  2. [app] [tier1] Group two (built by feature/2)" in prompt.splitlines()
