"""`config.AgentCommand`: one command a build agent may run (spec: toolchain-profiles)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from agent_build_kit.config import AgentCommand

VALID: dict[str, Any] = {"purpose": "test", "command": "uv run pytest -q"}


def test_a_string_command_is_split_into_argv() -> None:
    command = AgentCommand.model_validate(
        {**VALID, "command": "uv run pytest -q {path}", "scope": "file"}
    )

    assert command.command == ["uv", "run", "pytest", "-q", "{path}"]
    assert str(command.scope) == "file"
    listed = AgentCommand.model_validate({**VALID, "command": ["uv", "run", "pytest"]})
    assert listed.command == ["uv", "run", "pytest"], "a list is kept as it is"
    assert str(listed.scope) == "whole", "the scope defaults to whole"


@pytest.mark.parametrize(
    ("scope", "line"),
    [
        ("whole", "uv run pytest {path}"),
        ("file", "uv run pytest -q"),
        ("node-id", "uv run pytest -q"),
    ],
)
def test_the_path_word_is_required_unless_the_scope_is_whole(scope: str, line: str) -> None:
    AgentCommand.model_validate(VALID)  # the baseline loads

    with pytest.raises(ValidationError, match=r"\{path\}"):
        AgentCommand.model_validate({**VALID, "scope": scope, "command": line})


@pytest.mark.parametrize("scope", ["file", "node-id"])
def test_the_path_word_fits_a_scope_that_is_not_whole(scope: str) -> None:
    command = AgentCommand.model_validate({**VALID, "scope": scope, "command": "x {path}"})

    assert command.command == ["x", "{path}"]


@pytest.mark.parametrize(
    "bad",
    [{"purpose": "deploy"}, {"scope": "everywhere"}, {"extra": 1}],
    ids=["purpose", "scope", "key"],
)
def test_an_unknown_purpose_scope_or_key_is_refused(bad: dict[str, Any]) -> None:
    assert AgentCommand.model_validate(VALID).command == ["uv", "run", "pytest", "-q"]

    with pytest.raises(ValidationError):
        AgentCommand.model_validate({**VALID, **bad})


def test_the_model_is_frozen() -> None:
    command = AgentCommand.model_validate(VALID)
    assert command.command == ["uv", "run", "pytest", "-q"]

    with pytest.raises(ValidationError):
        command.command = ["other"]  # type: ignore[misc]
