"""What the test-writing prompt and the reviewer's checklist say about deterministic tests
(spec: flaky-tests): the same rules in both, in terms that name no language or tool."""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.stack_runner import TESTS_PROMPT
from agent_build_kit.pipeline.wiring import REVIEW_PROMPT
from tests.exclusions import rule_blocks

# What each rule says, as words the rule cannot be stated without.
RULES = {
    "the clock": ("sleep", "clock"),
    "an event": ("event",),
    "a thread nothing joins": ("thread", "join"),
    "a free port": ("free port", "fixed"),
    "a shared temporary path": ("temporary", "between tests"),
    "a state a background actor repairs": ("background", "repair"),
    "a step tests call directly": ("timer", "step", "directly"),
}

PROMPTS = [pytest.param(TESTS_PROMPT, id="tests"), pytest.param(REVIEW_PROMPT, id="review")]


@pytest.mark.parametrize("rule", RULES)
@pytest.mark.parametrize("prompt", PROMPTS)
def test_each_rule_is_in_the_prompt(prompt: str, rule: str) -> None:
    text = " ".join(rule_blocks(prompt))

    for word in RULES[rule]:
        assert word in text, f"the prompt does not say {rule!r}: no {word!r}"


def test_a_violation_a_change_introduces_is_a_required_finding_with_its_consequence() -> None:
    held = [b for b in rule_blocks(REVIEW_PROMPT) if "required" in b]

    assert held, "the reviewer's checklist makes a violation a required finding"
    assert "introduce" in held[0]
    assert "passes alone" in held[0]
    assert "fails under load" in held[0]
