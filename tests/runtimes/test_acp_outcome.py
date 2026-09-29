"""How the `acp` adapter runs one prompt, and reads how the turn ended.

The agent is a real subprocess speaking the protocol over stdio
(`acp_agent.py`), started from `runtimes.acp.command` as a workspace would
configure it. The protocol hands back an end-of-turn reason with the prompt's
response, so nothing here parses text for refusal markers:

- **Ended normally** is an answer: the final message's text.
- **A token or turn ceiling, or a refusal**, is a failed result carrying its
  reason, each distinguishable from the others.
- **Cancelled** is an interruption, which leaves the unit recoverable rather
  than failed.

Progress arrives as the agent's streamed updates, one line each, and a
callback that breaks never takes the run down with it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.runtimes import AgentInterrupted, AgentRequest, ToolPolicy
from agent_build_kit.runtimes.acp import AcpRuntime
from tests.runtimes.acp_agent import ANSWER, PREAMBLE, THOUGHT, TOOL_TITLE, requests, use_agent


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    path = tmp_path / "worktree"
    (path / "src").mkdir(parents=True)
    (path / "src" / "app.py").write_text("MARKER = None\n")
    return path


@pytest.fixture
def specs(tmp_path: Path) -> Path:
    path = tmp_path / "planning" / "openspec" / "specs"
    path.mkdir(parents=True)
    return path


def _request(worktree: Path, specs: Path, *, on_event=None) -> AgentRequest:
    return AgentRequest(
        prompt="Implement group 1 of add-marker.",
        role="implement",
        cwd=worktree,
        add_dirs=(specs,),
        policy=ToolPolicy(specs_dir=specs),
        on_event=on_event,
    )


def test_a_prompt_is_answered_with_the_agent_s_final_text(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    """The review step parses the answer as JSON, so it must be the message
    that closes the turn — joined from its streamed chunks — not the
    preamble before the tool call, and not the agent's thoughts."""
    record = tmp_path / "agent.jsonl"
    use_agent(record)

    result = AcpRuntime().run(_request(worktree, specs))

    assert result.ok is True
    assert result.text == ANSWER
    assert PREAMBLE not in result.text
    assert THOUGHT not in result.text
    assert result.error == ""
    assert result.stop_reason == "end_turn"
    [prompt] = requests(record, "session/prompt")
    assert [block["text"] for block in prompt["prompt"]] == ["Implement group 1 of add-marker."]


def test_the_session_works_in_the_worktree_and_can_read_the_extra_directories(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    """The agent works where the unit's branch is checked out, and the
    planning repo's specs are declared to it as readable roots beside it."""
    record = tmp_path / "agent.jsonl"
    use_agent(record)

    AcpRuntime().run(_request(worktree, specs))

    [initialized] = requests(record, "initialize")
    assert initialized["protocolVersion"] == 1
    [session] = requests(record, "session/new")
    assert session["cwd"] == str(worktree)
    assert session["additionalDirectories"] == [str(specs)]


@pytest.mark.parametrize("reason", ["max_tokens", "max_turn_requests", "refusal"])
def test_a_ceiling_or_a_refusal_is_a_failed_result_carrying_its_reason(
    tmp_path: Path, worktree: Path, specs: Path, reason: str
) -> None:
    use_agent(tmp_path / "agent.jsonl", stop=reason)

    result = AcpRuntime().run(_request(worktree, specs))

    assert result.ok is False
    assert result.stop_reason == reason
    assert result.error


def test_each_way_a_turn_fails_reads_differently(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    """A refusal and a ceiling call for different responses from whoever
    reads the unit's log, so no two of them may say the same thing."""
    errors = {}
    for reason in ("max_tokens", "max_turn_requests", "refusal"):
        use_agent(tmp_path / f"{reason}.jsonl", stop=reason)
        errors[reason] = AcpRuntime().run(_request(worktree, specs)).error

    assert len(set(errors.values())) == 3, errors


def test_a_cancelled_turn_is_an_interruption(tmp_path: Path, worktree: Path, specs: Path) -> None:
    """Cancelled says nothing about the work, so the unit is reclaimed rather
    than failed — the only ending that raises."""
    use_agent(tmp_path / "agent.jsonl", stop="cancelled")

    with pytest.raises(AgentInterrupted):
        AcpRuntime().run(_request(worktree, specs))


def test_streamed_messages_and_tool_calls_each_reach_the_progress_callback(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    """The tick log shows what a long run is doing as it does it: what the
    agent says, the tool call it starts, and how that call went."""
    lines: list[str] = []
    use_agent(tmp_path / "agent.jsonl")

    AcpRuntime().run(_request(worktree, specs, on_event=lines.append))

    said = [i for i, line in enumerate(lines) if PREAMBLE in line]
    started = [i for i, line in enumerate(lines) if TOOL_TITLE in line]
    assert said, lines
    assert started, lines
    assert any("completed" in line for line in lines[started[0] + 1 :]), lines
    assert said[0] < started[0]


def test_a_progress_callback_that_raises_does_not_fail_the_run(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    """Progress is for a reader; a broken log line is no reason to lose the
    work the agent did."""
    calls: list[str] = []

    def broken(line: str) -> None:
        calls.append(line)
        raise RuntimeError("the log is gone")

    use_agent(tmp_path / "agent.jsonl")

    result = AcpRuntime().run(_request(worktree, specs, on_event=broken))

    assert calls
    assert result.ok is True
    assert result.text == ANSWER
