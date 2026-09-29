"""The values a runtime is asked and answers with.

They are `model.Frozen` like every other value in this repo: a request handed
to a runtime cannot be changed underneath it, and a key nobody declared is a
mistake reported at construction rather than a flag silently dropped.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from agent_build_kit.runtimes import (
    AgentInterrupted,
    AgentRateLimited,
    AgentRequest,
    AgentResult,
    PolicyReport,
    ToolPolicy,
    UsageStatus,
)


def _request() -> AgentRequest:
    return AgentRequest(
        prompt="build it",
        role="implement",
        cwd=Path("/work/app"),
        add_dirs=(Path("/work/planning/openspec/specs"),),
        model="opus",
        allowed_tools="Bash(git status:*)",
        denied_tools="Bash(gh pr merge:*)",
        permission_mode="edit",
        policy=ToolPolicy(specs_dir=Path("/work/planning/openspec/specs")),
    )


def _values() -> list[BaseModel]:
    return [
        _request(),
        AgentResult(ok=False, text="", raw="{}", error="exit 1", stop_reason="refusal"),
        PolicyReport(ok=False, unenforced=("pushing to a default branch",), fix="constrain"),
        ToolPolicy(specs_dir=None, branch_prefix="spec/"),
        UsageStatus(
            session_pct=40,
            weekly_pct=12,
            resets_at=None,
            observed_at=datetime(2026, 9, 28, 3, tzinfo=UTC),
            source="cache",
        ),
    ]


@pytest.mark.parametrize("value", _values(), ids=lambda v: type(v).__name__)
def test_a_value_rejects_a_field_it_does_not_declare(value: BaseModel) -> None:
    """A runtime-specific flag smuggled in as a field is refused, not dropped."""
    fields = value.model_dump()
    fields["dangerously_skip_permissions"] = True

    with pytest.raises(ValidationError):
        type(value)(**fields)


@pytest.mark.parametrize("value", _values(), ids=lambda v: type(v).__name__)
def test_a_value_refuses_mutation(value: BaseModel) -> None:
    field = next(iter(type(value).model_fields))

    with pytest.raises(ValidationError):
        setattr(value, field, getattr(value, field))


def test_a_cancelled_turn_and_a_spent_window_are_told_apart() -> None:
    """An interruption says nothing about the work and is reclaimed; a spent
    usage window pauses the pipeline until it resets. A caller catching one
    must never catch the other."""
    resets = datetime(2026, 1, 1, 12, tzinfo=UTC)
    limited = AgentRateLimited("usage window spent", resets_at=resets)
    interrupted = AgentInterrupted("killed by a signal")

    assert limited.resets_at == resets
    assert AgentRateLimited("spent").resets_at is None
    assert not isinstance(limited, AgentInterrupted)
    assert not isinstance(interrupted, AgentRateLimited)

    with pytest.raises(AgentRateLimited):
        try:
            raise limited
        except AgentInterrupted:
            pytest.fail("a rate limit was caught as an interruption")
    with pytest.raises(AgentInterrupted):
        try:
            raise interrupted
        except AgentRateLimited:
            pytest.fail("an interruption was caught as a rate limit")
