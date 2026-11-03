"""The default commands a build agent is told it may run name the tests of one file or one test
id and the whole-repo lint, format and type checks, and no command that runs a repo's whole test
suite (spec: agent-test-commands). A repo that sets `agent_commands` gets exactly what it names."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import profiles
from agent_build_kit.config import AgentCommand, AgentPurpose, AgentScope
from agent_build_kit.pipeline.agent_commands import commands_note
from tests.agent_command_fakes import command, repo_of


def provided(name: str) -> tuple[AgentCommand, ...]:
    return getattr(profiles.get(name), "agent_commands", ())


def kinds(name: str) -> set[tuple[AgentPurpose, AgentScope]]:
    return {(item.purpose, item.scope) for item in provided(name)}


@pytest.mark.parametrize("name", ["python-uv", "node-npm"])
def test_a_default_profile_names_no_whole_repo_test_command(name: str) -> None:
    assert (AgentPurpose.TEST, AgentScope.WHOLE) not in kinds(name)
    assert (AgentPurpose.TEST, AgentScope.FILE) in kinds(name)


def test_python_uv_names_the_tests_of_a_file_and_of_a_test_id() -> None:
    assert {(AgentPurpose.TEST, AgentScope.FILE), (AgentPurpose.TEST, AgentScope.NODE_ID)} <= kinds(
        "python-uv"
    )


def test_python_uv_keeps_its_whole_repo_checks() -> None:
    assert (AgentPurpose.CHECK, AgentScope.WHOLE) in kinds("python-uv")


def test_node_npm_keeps_its_lint_format_and_type_checks() -> None:
    commands = {item.purpose for item in provided("node-npm")}

    assert {AgentPurpose.LINT, AgentPurpose.FORMAT, AgentPurpose.CHECK} <= commands


@pytest.mark.parametrize("profile", ["python-uv", "node-npm"])
def test_the_note_of_a_default_profile_has_no_whole_repo_test_line(
    tmp_path: Path, profile: str
) -> None:
    note = commands_note(repo_of(tmp_path, profile=profile))

    assert "test, whole repo" not in note
    assert "test, one file" in note


def test_a_repo_that_names_a_whole_suite_command_gets_it(tmp_path: Path) -> None:
    note = commands_note(repo_of(tmp_path, agent_commands=[command("test", "uv run pytest -q")]))

    assert "uv run pytest -q" in note
