"""What the regression agent, the builder and the reviewer are told about the tests that share a
failing test's cause (spec: regression-same-exposure).

The agent names the pattern, searches the test tree for it with read-only tools and marks each
test `confirmed` or `possible`; only the confirmed ones go in the tasks, with one standing line
naming the possible ones. The builder may fix a listed possible test it shows shares the cause,
and the reviewer accepts that edit. The agent is a stand-in; no model runs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import next_fix_name
from agent_build_kit.pipeline.regression_agent import TOOLS
from agent_build_kit.pipeline.stack_runner import (
    IMPLEMENTATION_PROMPT,
    REVIEW_FEEDBACK_PROMPT,
    REWORK_PROMPT,
    TESTS_PROMPT,
)
from agent_build_kit.pipeline.wiring import REVIEW_PROMPT
from agent_build_kit.runtimes import AgentRequest
from tests.prompt_text import flat
from tests.regression_agent_support import TEST, Attempts, run

POSSIBLE_LINE = (
    "Possible, in scope if you show they share the cause: <test ids>. "
    "Say which in the commit body and what showed it."
)
NONE_LINE = "Same exposure: none, the cause is specific to this test"
RUNNERS = re.compile(r"pytest|\buv\b|\bnpm\b|\bnpx\b|\bmake\b|\bpoe\b|Bash\(\*\)|^Bash$")


def agent_request(installation: Installation, tmp_path: Path) -> AgentRequest:
    agent = Attempts(installation, next_fix_name(installation, TEST), {})
    run(installation, tmp_path, agent.runtime)
    return agent.runtime.request


@pytest.fixture
def told(installation: Installation, tmp_path: Path) -> str:
    """What the regression agent is told, whitespace squeezed and lower-cased."""
    return flat(agent_request(installation, tmp_path).prompt).lower()


def paragraphs(prompt: str, marker: str) -> str:
    """The squeezed, lower-cased paragraphs or bullets of `prompt` that hold `marker`."""
    parts = re.split(r"\n\s*\n|\n- ", prompt)
    held = [flat(part).lower() for part in parts if marker in part.lower()]
    assert held, f"no paragraph of the prompt mentions {marker!r}"
    return " ".join(held)


# The regression agent


def test_the_agent_is_told_to_name_the_pattern_when_the_cause_is_one(told: str) -> None:
    assert "same exposure" in told
    assert "name the pattern" in told
    for shape in ("helper", "directory", "time budget", "shared"):
        assert shape in told


def test_the_agent_searches_the_test_tree_with_read_only_tools(told: str) -> None:
    assert "search the test tree" in told
    assert "read-only" in told
    assert "grep" in told


def test_the_agent_marks_each_test_confirmed_or_possible(told: str) -> None:
    assert "`confirmed`" in told
    assert "`possible`" in told


def test_only_the_confirmed_tests_are_in_the_tasks_with_one_line_for_the_possible_ones(
    installation: Installation, tmp_path: Path
) -> None:
    prompt = flat(agent_request(installation, tmp_path).prompt)

    assert flat(POSSIBLE_LINE) in prompt
    assert re.search(r"only the `?confirmed`? tests", prompt, re.IGNORECASE)


def test_a_cause_that_is_not_a_pattern_writes_the_none_form(told: str) -> None:
    assert NONE_LINE.lower() in told


def test_the_list_has_no_cap(told: str) -> None:
    assert re.search(r"(no|not any) (limit|cap)|do not (limit|cap)|every test", told)


def test_the_agent_is_not_asked_to_run_the_tests_and_is_given_no_tool_that_does(
    installation: Installation, tmp_path: Path
) -> None:
    request = agent_request(installation, tmp_path)

    assert re.search(r"do not run|never run|not run", flat(request.prompt).lower())
    # What follows `TOOLS` is the repo's own commands for running the one failing test (spec:
    # regression-agent); the listed tests are searched, not run, so nothing broader is granted.
    assert request.allowed_tools.startswith(TOOLS)
    for granted in TOOLS.split():
        assert not RUNNERS.search(granted), f"{granted} would run the listed tests"
    for granted in request.allowed_tools.removeprefix(TOOLS).split():
        assert not re.search(r"Bash\(\*\)|^Bash$", granted), f"{granted} would run anything"
    assert request.policy is not None and request.policy.sandbox is not None
    assert request.policy.sandbox.write == (request.planning_change_dir,)


# The builder and the reviewer

BUILDER = [
    pytest.param(TESTS_PROMPT, id="tests"),
    pytest.param(IMPLEMENTATION_PROMPT, id="implementation"),
    pytest.param(REWORK_PROMPT, id="rework"),
    pytest.param(REVIEW_FEEDBACK_PROMPT, id="review-feedback"),
]


@pytest.mark.parametrize("prompt", BUILDER)
def test_the_builder_may_fix_a_listed_possible_test_it_shows_shares_the_cause(
    prompt: str,
) -> None:
    rule = paragraphs(prompt, "possible")

    assert "share the cause" in rule
    assert "commit body" in rule
    assert "evidence" in rule or "what showed" in rule


@pytest.mark.parametrize("prompt", BUILDER)
def test_the_builder_may_not_edit_a_test_that_is_not_listed(prompt: str) -> None:
    rule = paragraphs(prompt, "possible")

    assert re.search(r"(not|never) edit a test the tasks neither name in a step nor list", rule)
    assert rule.startswith("if the tasks carry a line naming tests as possible"), (
        "the prohibition sits in the conditional paragraph, not on a line of its own"
    )


def test_the_reviewer_accepts_an_edit_to_a_listed_possible_test_with_its_evidence() -> None:
    rule = paragraphs(REVIEW_PROMPT, "possible")

    assert "in scope" in rule
    assert "commit body" in rule
    assert "evidence" in rule


def test_the_reviewer_requires_a_change_for_missing_evidence_or_an_unlisted_test() -> None:
    rule = paragraphs(REVIEW_PROMPT, "possible")

    assert re.search(r"(evidence|commit body)[^.]*(missing|absent|does not name)", rule)
    assert re.search(r"neither name in a step nor list as possible", rule)
    assert "required" in rule
