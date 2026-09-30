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

import contextlib
import json
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


def test_keep_record_returns_the_whole_exchange_as_one_json_line_each(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    """A track phase (`worktree=None`, `keep_record=True`) writes `raw` to its
    raw output file; under acp that must be the session's real traffic, not
    an empty string, since there is no other machine-readable record of it."""
    use_agent(tmp_path / "agent.jsonl")

    result = AcpRuntime().run(_request(worktree, specs, keep_record=True))

    assert result.ok is True
    lines = [json.loads(line) for line in result.raw.splitlines() if line]
    assert lines
    assert any(line.get("method") == "session/update" for line in lines)
    assert any(line.get("result", {}).get("stopReason") == "end_turn" for line in lines)


def test_a_ceiling_result_also_carries_its_raw_record(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    """The record is set once the agent has run, whether the turn ended
    normally or not — a held unit's raw output should still show what the
    agent said before it hit the ceiling."""
    use_agent(tmp_path / "agent.jsonl", stop="max_tokens")

    result = AcpRuntime().run(_request(worktree, specs, keep_record=True))

    assert result.ok is False
    lines = [json.loads(line) for line in result.raw.splitlines() if line]
    assert any(line.get("result", {}).get("stopReason") == "max_tokens" for line in lines)


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
    assert len(sessions) == 2
    # `exclude_none` drops an unset field from the wire entirely, so its
    # absence — not a `None` value — is what proves it was never sent.
    assert all("additionalDirectories" not in session for session in sessions)
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
    nothing of them reaches the agent, and the run goes ahead. Checked
    against the whole record, not just the calls expected to carry a tool
    list — the fields must not leak through `_meta`, `initialize` or
    `session/set_config_option` either. An edit-mode run naming an edit tool
    is the ordinary, advisory case (the run was going to edit anyway), so it
    is let through with one notice, not refused."""
    record = tmp_path / "agent.jsonl"
    use_agent(record)
    lines: list[str] = []

    result = AcpRuntime().run(
        _request(
            worktree,
            specs,
            allowed_tools="Read Edit Write Bash(uv run *)",
            denied_tools="WebFetch",
            on_event=lines.append,
        )
    )

    assert result.ok is True
    assert result.text == ANSWER
    sent = record.read_text()
    assert "Bash(uv run *)" not in sent
    assert "WebFetch" not in sent
    told = [line for line in lines if "allowed_tools" in line and "denied_tools" in line]
    assert len(told) == 1, lines


def test_a_read_only_shaped_request_is_refused_before_the_agent_is_spawned(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    """`wiring.build_run_review` sends an `edit`-mode request whose
    `allowed_tools` names no edit tool: on this runtime, ignoring that would
    let the reviewer edit the worktree it is judging, breaking the guarantee
    docs/architecture.md states as a property of the pipeline. Refused, and
    the agent never starts."""
    record = tmp_path / "agent.jsonl"
    use_agent(record)
    request = _request(
        worktree,
        specs,
        allowed_tools="Read Grep Glob Bash(git diff*) Bash(git log*) Bash(git show*)",
    ).model_copy(update={"role": "review"})

    result = AcpRuntime().run(request)

    assert result.ok is False
    assert "allowed_tools" in result.error
    assert "reviewer" in result.error and "edit" in result.error
    assert not record.exists()


def test_a_research_shaped_request_is_refused_before_the_agent_is_spawned(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    """`init.research.research` sends an `allowed_tools_only`-mode request
    whose `allowed_tools` names no edit tool — the same shape as a review
    run, just under a different `permission_mode`. On this runtime, ignoring
    that would let a run meant to be read-only edit the repo it is
    researching. Refused, and the agent never starts, same as review."""
    record = tmp_path / "agent.jsonl"
    use_agent(record)
    request = _request(
        worktree,
        specs,
        allowed_tools="Read Grep Glob WebSearch WebFetch",
        permission_mode="allowed_tools_only",
    )

    result = AcpRuntime().run(request)

    assert result.ok is False
    assert "allowed_tools" in result.error
    assert not record.exists()


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
    assert result.raw != ""


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
    assert result.raw != ""


def _gone(pid: int) -> bool:
    """Whether `pid` has exited. A zombie counts: once its parent is gone it
    waits on whatever adopted it to reap it, which need not be prompt."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        # It existed a moment ago and its entry is gone now: it exited and was
        # reaped in between. Read as "still running", this made a process that
        # died on time look like one that outlived the run.
        return True
    # The state follows the command name, which is in parentheses.
    return stat.rpartition(")")[2].split()[0] == "Z"


def _gone_soon(pid: int) -> bool:
    deadline = time.monotonic() + 5
    while not _gone(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    return _gone(pid)


def _kill_if_left(pid: int) -> None:
    """Clean up a process the run should have killed, if it is still there.

    It may exit on its own between the check and the kill, and a cleanup that
    raised then would hide the assertion that says what actually went wrong.
    """
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGKILL)


def _run_bounded(request: AgentRequest) -> tuple[AgentResult | None, float]:
    """Run on a thread, so a run that never returns fails the test instead of
    hanging it: the result, or None if it did not return, and how long it took."""
    results: list[AgentResult] = []
    run = threading.Thread(target=lambda: results.append(AcpRuntime().run(request)), daemon=True)
    started = time.monotonic()
    run.start()
    run.join(timeout=10)
    elapsed = time.monotonic() - started
    return (None if run.is_alive() else results[0]), elapsed


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

    result, elapsed = _run_bounded(_request(worktree, specs))
    orphan = int(orphan_pid_file(record).read_text())
    left = not _gone_soon(orphan)
    if left:
        _kill_if_left(orphan)

    assert result is not None, "run() did not return"
    assert elapsed < 5
    assert result.ok is False
    assert "killed" in result.error
    assert STDERR_LINE in result.error
    assert not left, "the agent's child outlived the run"


def test_a_process_out_of_reach_of_the_kill_does_not_hold_the_run_open(
    tmp_path: Path, worktree: Path, specs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A process the agent started in a session of its own escapes the kill
    of the agent's group and keeps stderr open for as long as it lives: the
    run stops waiting for stderr after the grace and ends all the same."""
    monkeypatch.setattr(acp, "EXIT_GRACE", 0.2)
    record = tmp_path / "agent.jsonl"
    use_agent(record, fail="detach")

    result, elapsed = _run_bounded(_request(worktree, specs))
    # Out of abk's reach by design, so the test cleans it up itself.
    detached = orphan_pid_file(record)
    if detached.exists():
        try:
            os.kill(int(detached.read_text()), signal.SIGKILL)
        except ProcessLookupError:
            pass

    assert result is not None, "run() did not return"
    assert elapsed < 5
    assert result.ok is False
    assert "killed" in result.error
    assert STDERR_LINE in result.error


def test_an_agent_that_ends_its_turn_but_leaves_stderr_held_has_that_holder_killed(
    tmp_path: Path, worktree: Path, specs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The agent answers and exits, but a process it started in its group
    still holds stderr: the answer stands, and that process is killed rather
    than left running after the tick."""
    monkeypatch.setattr(acp, "EXIT_GRACE", 0.2)
    record = tmp_path / "agent.jsonl"
    use_agent(record, linger=True)

    result, elapsed = _run_bounded(_request(worktree, specs))
    child = int(orphan_pid_file(record).read_text())
    left = not _gone_soon(child)
    if left:
        _kill_if_left(child)

    assert result is not None, "run() did not return"
    assert elapsed < 5
    assert result.ok is True
    assert result.text == ANSWER
    assert not left, "the agent's child outlived the run"


def test_an_error_answering_the_prompt_is_a_failed_result(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    use_agent(tmp_path / "agent.jsonl", fail="error")

    result = AcpRuntime().run(_request(worktree, specs))

    assert result.ok is False
    assert "the agent answered an error" in result.error
    assert result.raw != ""
