"""A runtime declares how it carries a prompt, and one check refuses a prompt over that
transport's safe size before any process starts (spec: prompt-delivery)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.acp import AcpRuntime
from agent_build_kit.runtimes.base import PromptTooLarge, PromptTransport, check_prompt_size
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime

ARGUMENT_LIMIT = 100_000
LARGE_LIMIT = 2_000_000


def first_line(error: pytest.ExceptionInfo[PromptTooLarge]) -> str:
    return str(error.value).splitlines()[0]


@pytest.mark.parametrize(
    ("transport", "limit"),
    [
        (PromptTransport.ARGUMENT, ARGUMENT_LIMIT),
        (PromptTransport.STDIN, LARGE_LIMIT),
        (PromptTransport.PROTOCOL, LARGE_LIMIT),
    ],
)
def test_a_prompt_of_exactly_the_safe_size_is_delivered_and_one_byte_more_is_refused(
    transport: PromptTransport, limit: int
) -> None:
    assert check_prompt_size(AgentRequest(prompt="x" * limit), transport) == limit

    with pytest.raises(PromptTooLarge):
        check_prompt_size(AgentRequest(prompt="x" * (limit + 1)), transport)


def test_the_size_is_counted_in_utf_8_bytes() -> None:
    prompt = "é" * 50_001

    with pytest.raises(PromptTooLarge) as refused:
        check_prompt_size(AgentRequest(prompt=prompt), PromptTransport.ARGUMENT)

    assert re.search(r"100,?002 bytes", first_line(refused))
    assert (
        check_prompt_size(AgentRequest(prompt=prompt[:50_000]), PromptTransport.ARGUMENT) == 100_000
    )


def test_the_refusal_names_the_role_the_size_the_limit_and_the_transport() -> None:
    request = AgentRequest(prompt="x" * 100_001, role="review")

    with pytest.raises(PromptTooLarge) as refused:
        check_prompt_size(request, PromptTransport.ARGUMENT)

    assert re.fullmatch(
        r"the review prompt is 100,?001 bytes; the argument transport carries at most 100,?000",
        first_line(refused),
    )


def test_the_refusal_names_the_change_when_the_request_names_one() -> None:
    request = AgentRequest(prompt="x" * 2_000_001, role="generic", change="add-marker")

    with pytest.raises(PromptTooLarge) as refused:
        check_prompt_size(request, PromptTransport.STDIN)

    assert "add-marker" in first_line(refused)
    assert re.search(r"2,?000,?001 bytes", first_line(refused))
    assert "stdin" in first_line(refused)


def test_each_runtime_declares_how_it_carries_a_prompt() -> None:
    assert getattr(ClaudeCodeRuntime(), "prompt_transport", None) == PromptTransport.STDIN
    assert getattr(AcpRuntime(), "prompt_transport", None) == PromptTransport.PROTOCOL


class ArgumentRuntime(ClaudeCodeRuntime):
    """A runtime that can carry a prompt only as an argument."""

    prompt_transport: PromptTransport = PromptTransport.ARGUMENT


def refusing_executor(*args, **kwargs) -> subprocess.CompletedProcess[str]:
    raise AssertionError("a process was started for a prompt that is too large")


def test_run_refuses_an_oversize_prompt_before_its_executor_is_called(tmp_path: Path) -> None:
    runtime = ArgumentRuntime(execute=refusing_executor)

    with pytest.raises(PromptTooLarge) as refused:
        runtime.run(AgentRequest(prompt="x" * 100_001, cwd=tmp_path))

    assert "Argument list too long" not in str(refused.value)
    assert re.search(r"100,?001 bytes", first_line(refused))
    assert "argument" in first_line(refused)


def test_run_refuses_a_prompt_over_the_stdin_size_before_its_executor_is_called() -> None:
    runtime = ClaudeCodeRuntime(execute=refusing_executor)

    with pytest.raises(PromptTooLarge) as refused:
        runtime.run(AgentRequest(prompt="x" * 2_000_001))

    assert "stdin" in first_line(refused)
