"""The commands the built-in profiles name for a build agent (spec: toolchain-profiles)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit import forges, profiles
from agent_build_kit.config import AgentCommand, RepoConfig
from agent_build_kit.pipeline import wiring
from agent_build_kit.pipeline.agent_commands import effective
from agent_build_kit.tool_patterns import allows
from tests.agent_command_fakes import Bare, line_of


def provided(name: str) -> tuple[AgentCommand, ...]:
    return getattr(profiles.get(name), "agent_commands", ())


def pairs(name: str) -> set[tuple[str, str]]:
    return {(str(c.purpose), str(c.scope)) for c in provided(name)}


def test_every_registered_profile_names_only_commands_its_own_tools_allow() -> None:
    assert provided("python-uv") and provided("node-npm"), "the built-in profiles name some"

    for name in profiles.names():
        profile = profiles.get(name)
        tools = wiring.allowed_tools(profile, forges.get("github"), [])
        for item in getattr(profile, "agent_commands", ()):
            assert allows(tools, line_of(item)), (name, line_of(item))


def test_the_python_profile_gives_test_and_check_at_whole_and_file_scope() -> None:
    lines = [" ".join(c.command) for c in provided("python-uv")]

    assert {
        ("test", "whole"),
        ("test", "file"),
        ("check", "whole"),
        ("check", "file"),
    } <= pairs("python-uv")
    assert "uv run pytest -q" in lines
    assert "uv run pytest -q {path}" in lines
    assert "uv run pre-commit run --all-files" in lines
    assert "uv run pre-commit run --files {path}" in lines


def test_the_node_profile_gives_test_lint_format_and_check_each_through_npx() -> None:
    commands = provided("node-npm")

    assert {"test", "lint", "format", "check"} <= {str(c.purpose) for c in commands}
    assert all(c.command[0] == "npx" for c in commands)


def test_a_profile_without_the_attribute_gives_none(tmp_path: Path) -> None:
    with profiles.registered(Bare()):  # type: ignore[arg-type]
        repo = RepoConfig(path=tmp_path, slug="example/app", profile="fake-bare")

        assert effective(repo) == []
