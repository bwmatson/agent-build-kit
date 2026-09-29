"""How the `acp` adapter runs one prompt, and reads how the turn ended.

The agent is a real subprocess speaking the protocol over stdio
(`acp_agent.py`), started from `runtimes.acp.command` as a workspace would
configure it. The protocol hands back an end-of-turn reason with the prompt's
response, so nothing here parses text for refusal markers:

- **Ended normally** is an answer: the final message's text.
- **A token or turn ceiling, or a refusal**, is a failed result carrying its
  reason, each distinguishable from the others.
- **Cancelled**, or the agent killed by a signal from elsewhere, is an
  interruption, which leaves the unit recoverable rather than failed.
- **Anything else that goes wrong** — no agent configured, one that will not
  start, exits, answers an error, or lingers after its stdio goes and has to
  be killed by abk — is a failed result, never a bare exception.

Progress arrives as the agent's streamed updates: a message as one line
however many chunks it streamed in, each tool call's start and status as
their own. A callback that breaks never takes the run down with it.
"""

from __future__ import annotations

import os
import signal
import threading
import time
from pathlib import Path

import pytest

from agent_build_kit.runtimes import AgentInterrupted, AgentRequest, AgentResult, ToolPolicy, acp
from agent_build_kit.runtimes.acp import AcpRuntime
from tests.runtimes.acp_agent import (
    ANSWER,
    PREAMBLE,
    PREAMBLE_CHUNKS,
    STDERR_LINE,
    THOUGHT,
    TOOL_TITLE,
    orphan_pid_file,
    requests,
    use_agent,
    use_command,
)


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


def _request(worktree: Path, specs: Path, *, on_event=None, **fields) -> AgentRequest:
    return AgentRequest(
        prompt="Implement group 1 of add-marker.",
        role="implement",
        cwd=worktree,
        add_dirs=(specs,),
        policy=ToolPolicy(specs_dir=specs),
        on_event=on_event,
        **fields,
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


def test_extra_directories_go_only_to_an_agent_that_takes_them(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    """The field is gated on the agent's `additionalDirectories` session
    capability: one that does not advertise it may drop the field silently,
    so it is not sent, and the operator is told once instead."""
    record = tmp_path / "agent.jsonl"
    use_agent(record, additional_dirs=False)
    lines: list[str] = []
    runtime = AcpRuntime()

    result = runtime.run(_request(worktree, specs, on_event=lines.append))
    runtime.run(_request(worktree, specs, on_event=lines.append))

    assert result.ok is True
    sessions = requests(record, "session/new")
    assert [session["additionalDirectories"] for session in sessions] == [None, None]
    told = [line for line in lines if str(specs) in line]
    assert len(told) == 1, lines


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
    assert len(said) == 1, lines
    assert started, lines
    assert any("completed" in line for line in lines[started[0] + 1 :]), lines
    assert said[0] < started[0]
    # The preamble streamed a word at a time, and reads as one line.
    fragments = [
        line for line in lines if PREAMBLE not in line and any(w in line for w in PREAMBLE_CHUNKS)
    ]
    assert not fragments, lines
    assert sum(ANSWER in line for line in lines) == 1, lines


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


def test_a_step_that_passes_tool_lists_runs_and_the_lists_are_ignored(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    """The protocol has no per-session tool list, so both fields are inert:
    nothing of them reaches the agent, and the run goes ahead."""
    record = tmp_path / "agent.jsonl"
    use_agent(record)

    result = AcpRuntime().run(
        _request(worktree, specs, allowed_tools="Bash(uv run *)", denied_tools="WebFetch")
    )

    assert result.ok is True
    assert result.text == ANSWER
    sent = str(requests(record, "session/new")) + str(requests(record, "session/prompt"))
    assert "Bash(uv run *)" not in sent
    assert "WebFetch" not in sent


def test_a_named_worktree_is_refused_without_starting_the_agent(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    """A track phase asks for a checkout of its own; running it in cwd instead
    would put it in the planning checkout."""
    record = tmp_path / "agent.jsonl"
    use_agent(record)

    request = _request(worktree, specs).model_copy(update={"worktree": "track-health"})

    result = AcpRuntime().run(request)

    assert result.ok is False
    assert "worktree" in result.error
    assert not record.exists()


def test_no_command_configured_is_a_failed_result_naming_the_setting(
    worktree: Path, specs: Path
) -> None:
    use_command(None)

    result = AcpRuntime().run(_request(worktree, specs))

    assert result.ok is False
    assert "runtimes.acp.command" in result.error


def test_a_command_that_does_not_exist_is_a_failed_result(worktree: Path, specs: Path) -> None:
    use_command(["/nonexistent/agent"])

    result = AcpRuntime().run(_request(worktree, specs))

    assert result.ok is False
    assert "could not start" in result.error


def test_an_agent_that_exits_mid_turn_is_a_failed_result_carrying_its_stderr(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    use_agent(tmp_path / "agent.jsonl", fail="exit")

    result = AcpRuntime().run(_request(worktree, specs))

    assert result.ok is False
    assert STDERR_LINE in result.error


def test_an_agent_killed_by_a_signal_is_an_interruption(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    """A kill says nothing about the work, as with the other runtime."""
    use_agent(tmp_path / "agent.jsonl", fail="kill")

    with pytest.raises(AgentInterrupted, match="signal 9"):
        AcpRuntime().run(_request(worktree, specs))


def test_an_agent_abk_had_to_kill_is_a_failed_result_not_an_interruption(
    tmp_path: Path, worktree: Path, specs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its stdio went away but the process lingered, so abk killed it: that
    signal is abk's own and says the agent broke, so the unit fails with the
    agent's stderr rather than being reclaimed to break the same way again."""
    monkeypatch.setattr(acp, "EXIT_GRACE", 0.2)
    use_agent(tmp_path / "agent.jsonl", fail="hang")

    result = AcpRuntime().run(_request(worktree, specs))

    assert result.ok is False
    assert "killed" in result.error
    assert STDERR_LINE in result.error


def _gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def test_an_agent_that_leaves_a_process_holding_its_pipes_still_ends_the_run(
    tmp_path: Path, worktree: Path, specs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wrapper (a script, `npx`, `uvx`) forks the real agent, which holds
    the pipes too: killing only the wrapper leaves them open, and a tick
    waiting for their end would never finish. The whole agent is killed, and
    the wait for its stderr is bounded either way."""
    monkeypatch.setattr(acp, "EXIT_GRACE", 0.2)
    record = tmp_path / "agent.jsonl"
    use_agent(record, fail="orphan")
    results: list[AgentResult] = []
    run = threading.Thread(
        target=lambda: results.append(AcpRuntime().run(_request(worktree, specs))), daemon=True
    )

    started = time.monotonic()
    run.start()
    run.join(timeout=10)
    elapsed = time.monotonic() - started
    orphan = int(orphan_pid_file(record).read_text())
    deadline = time.monotonic() + 5
    while not _gone(orphan) and time.monotonic() < deadline:
        time.sleep(0.05)
    left = not _gone(orphan)
    if left:
        os.kill(orphan, signal.SIGKILL)

    assert not run.is_alive(), "run() did not return"
    assert elapsed < 5
    [result] = results
    assert result.ok is False
    assert "killed" in result.error
    assert STDERR_LINE in result.error
    assert not left, "the agent's child outlived the run"


def test_an_error_answering_the_prompt_is_a_failed_result(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    use_agent(tmp_path / "agent.jsonl", fail="error")

    result = AcpRuntime().run(_request(worktree, specs))

    assert result.ok is False
    assert "the agent answered an error" in result.error
