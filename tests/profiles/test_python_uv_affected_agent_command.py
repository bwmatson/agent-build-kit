"""Python-uv build agents have a command for the tests their edits affect (spec:
agent-test-commands): the profile defaults hold the testmon selection under the scope `affected`,
the commands section shows it as "tests your edits affect", the doctor's allow-list check passes
it, the regression agent is not granted it, and no prompt mentions it."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_build_kit import profiles
from agent_build_kit.config import AgentCommand, AgentPurpose, AgentScope
from agent_build_kit.pipeline import stack_runner
from agent_build_kit.pipeline.agent_commands import commands_note, refused
from agent_build_kit.pipeline.regression_agent import allowed_tools
from agent_build_kit.pipeline.scratch import output_convention
from tests.agent_command_fakes import repo_of
from tests.conftest import make_installation

AFFECTED = "uv run --with pytest-testmon pytest -q --testmon-forceselect --testmon-env=ctrace"
PROMPTS = [
    "TESTS_PROMPT",
    "IMPLEMENTATION_PROMPT",
    "IMPLEMENTATION_CONTINUATION",
    "REWORK_PROMPT",
    "REVIEW_FEEDBACK_PROMPT",
    "ADAPT_PROMPT",
    "ADAPT_CONTINUATION",
    "CHECKS_PROMPT",
    "CHECKS_CONTINUATION",
]


def provided(name: str) -> tuple[AgentCommand, ...]:
    return getattr(profiles.get(name), "agent_commands", ())


def test_the_python_uv_defaults_hold_the_selection_command_under_the_affected_scope() -> None:
    [found] = [item for item in provided("python-uv") if item.scope is AgentScope.AFFECTED]

    assert found.purpose is AgentPurpose.TEST
    assert " ".join(found.command) == AFFECTED


def test_the_node_npm_defaults_hold_no_affected_command() -> None:
    assert all(item.scope is not AgentScope.AFFECTED for item in provided("node-npm"))


def test_the_affected_scope_needs_no_path_and_refuses_one() -> None:
    made = AgentCommand.model_validate(
        {"purpose": "test", "command": AFFECTED, "scope": "affected"}
    )

    assert made.scope is AgentScope.AFFECTED
    with pytest.raises(ValidationError):
        AgentCommand.model_validate(
            {"purpose": "test", "command": f"{AFFECTED} {{path}}", "scope": "affected"}
        )


def test_the_commands_section_shows_it_as_the_tests_the_edits_affect(tmp_path: Path) -> None:
    note = commands_note(repo_of(tmp_path))

    assert f"- test, tests your edits affect: {AFFECTED}\n" in note
    assert "whole repo: uv run --with" not in note


def test_the_python_defaults_pass_the_allow_list_check(tmp_path: Path) -> None:
    assert refused(repo_of(tmp_path)) == []


def test_the_regression_agent_is_not_granted_the_affected_command(tmp_path: Path) -> None:
    installation = make_installation(tmp_path)

    tools = allowed_tools(installation, "app")

    assert "pytest-testmon" not in tools
    assert "Bash(uv run pytest -q *)" in tools


@pytest.mark.parametrize("name", PROMPTS)
def test_no_prompt_mentions_the_affected_command_or_testmon(name: str) -> None:
    assert "testmon" not in str(getattr(stack_runner, name)).lower()


def test_the_output_convention_does_not_mention_testmon() -> None:
    assert "testmon" not in output_convention().lower()
