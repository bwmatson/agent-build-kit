"""The roles are one list and every call names its role (spec: roles).

The request is built from a dict so a test names a role the way a configuration or a ledger row
does, whatever type the field has."""

from __future__ import annotations

import subprocess
from enum import Enum
from typing import get_args

import pytest
from pydantic import ValidationError

from agent_build_kit.installation import Installation
from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.claude_code import refresh_login
from tests.call_rows import agent_rows

ROLES = {
    "implement",
    "rework",
    "review",
    "rework_review",
    "regression",
    "plan",
    "restack",
    "login_refresh",
}


def role_names() -> set[str]:
    """The names the request's role accepts, read off its annotation whether it is a literal or
    an enum."""
    annotation = AgentRequest.model_fields["role"].annotation
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return {str(member.value) for member in annotation}
    return {str(name) for name in get_args(annotation)}


def test_the_roles_are_the_eight_and_there_is_no_generic() -> None:
    assert role_names() == ROLES


def test_a_request_cannot_be_built_without_a_role() -> None:
    with pytest.raises(ValidationError):
        AgentRequest.model_validate(dict(prompt="go"))


def test_a_request_naming_generic_is_refused() -> None:
    with pytest.raises(ValidationError):
        AgentRequest.model_validate(dict(prompt="go", role="generic"))


def test_the_login_refresh_row_names_its_own_role(workspace: Installation) -> None:
    def run(argv, **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, "", "")

    refresh_login(run=run)

    (row,) = agent_rows(workspace)
    assert (row["node"], row["role"]) == ("login_refresh", "login_refresh")
