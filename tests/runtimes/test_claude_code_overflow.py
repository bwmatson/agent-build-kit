"""A resumed Claude Code call whose context no longer fits is a session that cannot be
continued, so the node falls back to a new one (docs/unit-graph.md, Session capture and
resume)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.base import SessionUnavailable
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.runtimes.claude_cli import SESSION, FakeClaude, refused

OVERFLOW = "Prompt is too long"


def request(cwd: Path, **fields: object) -> AgentRequest:
    return AgentRequest(prompt="Continue.", role="implement", cwd=cwd, **fields)  # pyrefly: ignore


def test_a_resumed_call_that_overflows_its_context_is_unavailable(tmp_path: Path) -> None:
    fake = FakeClaude(stdout=refused(tmp_path, OVERFLOW), returncode=1)

    with pytest.raises(SessionUnavailable):
        ClaudeCodeRuntime(execute=fake).run(request(tmp_path, resume_session=SESSION))


def test_a_new_call_that_overflows_is_a_failed_result_not_an_unavailable_session(
    tmp_path: Path,
) -> None:
    fake = FakeClaude(stdout=refused(tmp_path, OVERFLOW), returncode=1)

    result = ClaudeCodeRuntime(execute=fake).run(request(tmp_path))

    assert not result.ok
