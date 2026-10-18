"""Toolchain profiles with their own agent commands, and the allow-list a command is judged by.

They live here and not in a test file, and name no method `test_*`, because the pipeline takes
any such name for a test.
"""

from __future__ import annotations

from typing import Any

from agent_build_kit.config import AgentCommand
from agent_build_kit.profiles.python_uv import PythonUvProfile


def command(purpose: str, line: str, scope: str = "whole") -> AgentCommand:
    return AgentCommand.model_validate(
        {"purpose": purpose, "command": line.split(), "scope": scope}
    )


class Silent(PythonUvProfile):
    """A profile that names no commands."""

    name = "fake-silent"
    agent_commands = ()


class Outside(PythonUvProfile):
    """A profile whose own command is outside its own `allowed_tools`."""

    name = "fake-outside"
    allowed_tools = "Bash(uv run *)"

    @property
    def agent_commands(self) -> tuple[AgentCommand, ...]:  # type: ignore[override]
        return (command("test", "uv run pytest -q"), command("lint", "ruff check ."))


class Bare:
    """A profile registered without the optional attribute, as a third party's may be."""

    name = "fake-bare"

    def __init__(self) -> None:
        self._inner = PythonUvProfile()

    def __getattr__(self, attribute: str) -> Any:
        if attribute == "agent_commands":
            raise AttributeError(attribute)
        return getattr(self._inner, attribute)
