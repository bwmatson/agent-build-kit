"""A `claude` run that ends on a 5xx from the model service raises, not fails.

The closing event's `api_error_status` is read first; the CLI's own words `API Error: <status>`
only when it is null. The exception carries the status and the words, and the call's spend is
told through `on_result` first. Every other status keeps failing the run, and a 429 stays a
refusal of the usage window.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.runtimes import (
    AgentRateLimited,
    AgentRequest,
    AgentResult,
    ServiceUnavailable,
    ToolPolicy,
)
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.runtimes.claude_cli import FakeClaude, refused

OVERLOADED = 'API Error: 529 {"type":"error","error":{"type":"overloaded_error"}}'
REFUSAL = "I can't help with that request."


def _request(cwd: Path, told: list[AgentResult]) -> AgentRequest:
    return AgentRequest(
        prompt="Implement group 1 of add-marker.",
        role="implement",
        cwd=cwd,
        add_dirs=(cwd / "specs",),
        model="opus",
        allowed_tools="Read Edit Write",
        policy=ToolPolicy(specs_dir=cwd / "specs"),
        on_event=lambda line: None,
        on_result=told.append,
    )


def _run(tmp_path: Path, text: str, status: int | None, told: list[AgentResult]) -> AgentResult:
    fake = FakeClaude(stdout=refused(tmp_path, text, api_error_status=status), returncode=1)
    return ClaudeCodeRuntime(execute=fake).run(_request(tmp_path, told))


@pytest.mark.parametrize("status", [529, 500, 503])
def test_a_closing_status_in_the_5xx_range_raises_with_the_status_and_the_words(
    tmp_path: Path, status: int
) -> None:
    told: list[AgentResult] = []

    with pytest.raises(ServiceUnavailable) as caught:
        _run(tmp_path, "API Error: the service is busy", status, told)

    assert caught.value.status == status
    assert "the service is busy" in str(caught.value)
    assert len(told) == 1, "the spend of the call is reported before the raise"


def test_a_null_status_with_the_words_of_a_529_raises_with_that_status(tmp_path: Path) -> None:
    told: list[AgentResult] = []

    with pytest.raises(ServiceUnavailable) as caught:
        _run(tmp_path, OVERLOADED, None, told)

    assert caught.value.status == 529
    assert "overloaded_error" in str(caught.value)
    assert len(told) == 1


def test_the_structured_status_is_read_before_the_words(tmp_path: Path) -> None:
    with pytest.raises(ServiceUnavailable) as caught:
        _run(tmp_path, "API Error: 400 bad request", 503, [])

    assert caught.value.status == 503


def test_every_other_ending_keeps_its_outcome(tmp_path: Path) -> None:
    with pytest.raises(ServiceUnavailable):
        _run(tmp_path, "API Error: the service is busy", 500, [])

    for status in (401, 403, 404):
        result = _run(tmp_path, f"API Error: {status} not allowed", status, [])
        assert result.ok is False
        assert f"{status} not allowed" in result.error

    refusal = _run(tmp_path, REFUSAL, None, [])
    assert refusal.ok is False
    assert REFUSAL in refusal.error

    with pytest.raises(AgentRateLimited):
        _run(tmp_path, "API Error: the request was refused, try again shortly", 429, [])

    assert _run(tmp_path, "API Error: the connection closed early", None, []).ok is False
