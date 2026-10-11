"""What the test-writing prompt and the reviewer's checklist say about deterministic tests
(spec: flaky-tests): the same rules in both, in terms that name no language or tool."""

from __future__ import annotations

import re

import pytest

from agent_build_kit.pipeline.stack_runner import TESTS_PROMPT
from agent_build_kit.pipeline.wiring import REVIEW_PROMPT

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

# A language, runner or library a rule must not be written in.
TOOLS = ("python", "pytest", "time.sleep", "asyncio", "unittest", "threading", "tmp_path", "jest")

PROMPTS = [pytest.param(TESTS_PROMPT, id="tests"), pytest.param(REVIEW_PROMPT, id="review")]


def squeezed(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def rule_blocks(prompt: str) -> list[str]:
    """The paragraphs and bullets of `prompt` that hold the determinism rules."""
    blocks = [squeezed(b) for b in re.split(r"\n\s*\n|\n- ", prompt)]
    return [b for b in blocks if "sleep" in b or "free port" in b or "background" in b]


@pytest.mark.parametrize("rule", RULES)
@pytest.mark.parametrize("prompt", PROMPTS)
def test_each_rule_is_in_the_prompt(prompt: str, rule: str) -> None:
    text = " ".join(rule_blocks(prompt))

    for word in RULES[rule]:
        assert word in text, f"the prompt does not say {rule!r}: no {word!r}"


@pytest.mark.parametrize("prompt", PROMPTS)
def test_the_rules_name_no_language_or_tool(prompt: str) -> None:
    blocks = rule_blocks(prompt)

    assert blocks, "the prompt carries the rules"
    for block in blocks:
        for tool in TOOLS:
            assert tool not in block, f"a rule names {tool!r}"


def test_a_violation_a_change_introduces_is_a_required_finding_with_its_consequence() -> None:
    held = [b for b in rule_blocks(REVIEW_PROMPT) if "required" in b]

    assert held, "the reviewer's checklist makes a violation a required finding"
    assert "introduce" in held[0]
    assert "passes alone" in held[0]
    assert "fails under load" in held[0]
