"""The roles, read from the one definition (`runtimes.base.Role`), for tests that go through every
role. A test names no literal list of roles, so a role added there is covered at once."""

from __future__ import annotations

from enum import Enum
from typing import get_args

from agent_build_kit.runtimes import AgentRequest


def role_names() -> tuple[str, ...]:
    """The names the request's role accepts, in definition order, whether the field is a literal
    or an enum."""
    annotation = AgentRequest.model_fields["role"].annotation
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return tuple(str(member.value) for member in annotation)
    return tuple(str(name) for name in get_args(annotation))


ROLES = role_names()
