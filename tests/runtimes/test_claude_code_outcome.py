"""How the Claude Code adapter reads what the CLI hands back.

Every call site used to interpret a finished `claude` process for itself, and
three of them disagreed. The adapter is now the one place that does, and the
four outcomes stay apart:

- **An answer.** The streamed `result` event's text — what plain `-p` would
  have printed — with each step of progress passed on as it happens.
- **A spent usage window**, raised with its reset time so the pipeline pauses
  until then instead of failing the unit.
- **An interruption.** The process was killed, which says nothing about the
  work; the unit is reclaimed, not failed.
- **Anything else** is a failed result, not an exception a caller has to
  guess the meaning of.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.pipeline.claude_stream import final_text
from agent_build_kit.runtimes import (
    AgentInterrupted,
    AgentRateLimited,
    AgentRequest,
    ToolPolicy,
    claude_code,
)
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.runtimes.claude_cli import (
    FakeClaude,
    failed_build,
    finished_build,
    record,
    refused,
    stream,
)


def _request(cwd: Path, *, on_event=None) -> AgentRequest:
    return AgentRequest(
        prompt="Implement group 1 of add-marker.",
        role="implement",
        cwd=cwd,
        add_dirs=(cwd / "specs",),
        model="opus",
        allowed_tools="Read Edit Write",
        policy=ToolPolicy(specs_dir=cwd / "specs"),
        on_event=on_event or (lambda line: None),
    )


def test_a_streamed_run_answers_with_the_result_event_s_text(tmp_path: Path) -> None:
    """The review step parses this answer as JSON, so it must be the result
    text alone, not the stream it arrived in."""
    answer = '{"approved": true, "feedback": "", "needs_human": false}'
    fake = FakeClaude(stdout=finished_build(tmp_path, answer))

    result = ClaudeCodeRuntime(execute=fake).run(_request(tmp_path))

    assert result.ok is True
    assert result.text == answer
    assert json.loads(result.text)["approved"] is True
    assert result.raw == fake.stdout
    assert result.error == ""


def test_each_step_of_a_streamed_run_reaches_the_progress_callback(tmp_path: Path) -> None:
    """The tick log shows what a twenty-minute run is doing: what the model
    says and which tool it calls on what, relative to the worktree, whose
    absolute path would be the same long prefix on every line."""
    lines: list[str] = []
    fake = FakeClaude(stdout=finished_build(tmp_path, "done"))

    ClaudeCodeRuntime(execute=fake).run(_request(tmp_path, on_event=lines.append))

    said = [line.strip() for line in lines]
    assert said[0] == "claude started (claude-opus-5-5)"
    assert "says: I'll add the marker to the app module." in said
    assert "Edit src/app.py" in said
    assert said[-1] == "claude done — 3 turns, 1m21s"
    assert not any(str(tmp_path) in line for line in lines)


def test_a_spent_usage_window_raises_with_its_reset_time(tmp_path: Path) -> None:
    fake = FakeClaude(
        stdout=refused(tmp_path, "Claude AI usage limit reached|1919763200"), returncode=1
    )

    with pytest.raises(AgentRateLimited) as caught:
        ClaudeCodeRuntime(execute=fake).run(_request(tmp_path))

    assert caught.value.resets_at == datetime.fromtimestamp(1919763200, UTC)


def test_a_refusal_that_does_not_say_when_it_lifts_still_raises(tmp_path: Path) -> None:
    """No timestamp must not read as "not rate limited": the live usage
    reading supplies the time instead."""
    fake = FakeClaude(
        stdout=refused(tmp_path, "API Error: 429 rate_limit_error"),
        returncode=1,
        stderr="",
    )

    with pytest.raises(AgentRateLimited) as caught:
        ClaudeCodeRuntime(execute=fake).run(_request(tmp_path))

    assert caught.value.resets_at is None


def test_a_clean_exit_with_a_rate_limited_closing_event_still_raises(tmp_path: Path) -> None:
    fake = FakeClaude(
        stdout=refused(tmp_path, "Claude AI usage limit reached|1919763200"), returncode=0
    )

    with pytest.raises(AgentRateLimited) as caught:
        ClaudeCodeRuntime(execute=fake).run(_request(tmp_path))

    assert caught.value.resets_at == datetime.fromtimestamp(1919763200, UTC)


def test_a_clean_exit_with_an_error_closing_event_is_a_failed_result(tmp_path: Path) -> None:
    fake = FakeClaude(stdout=failed_build(tmp_path, "Reached maximum turns"), returncode=0)

    outcome = ClaudeCodeRuntime(execute=fake).run(_request(tmp_path))

    assert not outcome.ok
    assert outcome.stop_reason.startswith("error")


def test_a_process_killed_by_a_signal_is_an_interruption(tmp_path: Path) -> None:
    """A run killed seconds in says nothing about the work; failing the unit
    would untick its tasks for no reason."""
    started = stream(json.loads(finished_build(tmp_path, "done").splitlines()[0]))
    fake = FakeClaude(stdout=started, returncode=-9)

    with pytest.raises(AgentInterrupted, match="9"):
        ClaudeCodeRuntime(execute=fake).run(_request(tmp_path))


def test_any_other_failed_exit_is_a_failed_result(tmp_path: Path) -> None:
    """Not an exception: the caller decides what a broken run means for its
    step, and is told why — in the CLI's own words, not the transcript."""
    fake = FakeClaude(
        stdout=failed_build(tmp_path, "Execution error: the Edit tool could not write the file"),
        returncode=1,
    )

    result = ClaudeCodeRuntime(execute=fake).run(_request(tmp_path))

    assert result.ok is False
    assert (
        result.error == "claude exited 1: Execution error: the Edit tool could not write the file"
    )
    assert result.stop_reason == "error_during_execution"
    assert result.raw == fake.stdout


def test_a_failed_run_s_text_is_not_its_transcript(tmp_path: Path) -> None:
    """An error-subtype result carries no answer; the transcript stays in
    `raw` and nowhere else."""
    fake = FakeClaude(stdout=failed_build(tmp_path, "Execution error"), returncode=1)

    result = ClaudeCodeRuntime(execute=fake).run(_request(tmp_path))

    assert result.text == ""
    assert result.raw == fake.stdout


def test_a_refusal_reported_in_the_result_s_errors_raises(tmp_path: Path) -> None:
    """An error-subtype result has no `result` text: what went wrong is in
    its `errors`, and a refusal there is still a refusal."""
    fake = FakeClaude(
        stdout=failed_build(
            tmp_path, 'API Error: 429 {"type":"error","error":{"type":"rate_limit_error"}}'
        ),
        returncode=1,
    )

    with pytest.raises(AgentRateLimited):
        ClaudeCodeRuntime(execute=fake).run(_request(tmp_path))


def test_a_failure_is_never_read_as_a_rate_limit_or_an_interruption(tmp_path: Path) -> None:
    fake = FakeClaude(
        stdout=failed_build(tmp_path, "Execution error"),
        returncode=2,
        stderr="error: could not resolve host github.com",
    )

    result = ClaudeCodeRuntime(execute=fake).run(_request(tmp_path))

    assert result.ok is False
    assert "could not resolve host" in result.error


def test_a_transcript_that_mentions_rate_limits_is_not_a_refusal(tmp_path: Path) -> None:
    """A stream carries every event's uuid, the files the agent read and its
    own prose. A build of rate-limit code has "429" and "rate limit" all over
    it; only the result event and stderr say whether the account refused."""
    stdout = failed_build(tmp_path, "Execution error: the Edit tool could not write the file")
    assert "429" in stdout
    assert "rate limit" in stdout
    fake = FakeClaude(stdout=stdout, returncode=1)

    result = ClaudeCodeRuntime(execute=fake).run(_request(tmp_path))

    assert result.ok is False
    assert "429" not in result.error


def test_a_run_that_is_not_a_stream_is_classified_on_its_text(tmp_path: Path) -> None:
    """Plain `-p` prints no events: what it printed is what it said."""
    fake = FakeClaude(stdout="Claude AI usage limit reached|1919763200\n", returncode=1)
    request = AgentRequest(prompt="Plan.", permission_mode="allowed_tools_only")

    with pytest.raises(AgentRateLimited) as caught:
        ClaudeCodeRuntime(execute=fake).run(request)

    assert caught.value.resets_at == datetime.fromtimestamp(1919763200, UTC)


def test_a_refusal_on_stderr_is_still_a_refusal(tmp_path: Path) -> None:
    started = stream(json.loads(finished_build(tmp_path, "done").splitlines()[0]))
    fake = FakeClaude(stdout=started, returncode=1, stderr="API Error: 429 rate_limit_error")

    with pytest.raises(AgentRateLimited):
        ClaudeCodeRuntime(execute=fake).run(_request(tmp_path))


def test_a_kept_record_is_the_raw_output_and_its_answer_the_text(tmp_path: Path) -> None:
    """A track phase writes the whole record to its raw output file and reads
    the answer out of it."""
    fake = FakeClaude(stdout=record("No findings."))
    request = AgentRequest(prompt="Run the health track for app.", cwd=tmp_path, keep_record=True)

    result = ClaudeCodeRuntime(execute=fake).run(request)

    assert result.ok is True
    assert result.text == "No findings."
    assert result.raw == fake.stdout
    kept = json.loads(result.raw)
    assert kept["session_id"] and kept["total_cost_usd"] and kept["usage"]


def test_streaming_wins_over_a_kept_record(tmp_path: Path) -> None:
    """Asked for both, the run streams: `raw` is its event lines, not the
    single JSON record."""
    fake = FakeClaude(stdout=finished_build(tmp_path, "done"))
    request = AgentRequest(
        prompt="Implement.", cwd=tmp_path, on_event=lambda line: None, keep_record=True
    )

    result = ClaudeCodeRuntime(execute=fake).run(request)

    assert fake.argv[fake.argv.index("--output-format") + 1] == "stream-json"
    assert result.text == "done"
    assert len(result.raw.splitlines()) > 1


def test_a_finished_run_says_how_it_ended(tmp_path: Path) -> None:
    fake = FakeClaude(stdout=finished_build(tmp_path, "done"))

    result = ClaudeCodeRuntime(execute=fake).run(_request(tmp_path))

    assert result.stop_reason == "success"


# Bound at import, before `no_real_agent` swaps the module attribute out.
_real_spawn = claude_code.spawn
_PRINTS_TWO_EVENTS = (
    "import json; "
    "print(json.dumps({'type': 'system', 'subtype': 'init'})); "
    "print(json.dumps({'type': 'result', 'result': 'ok'}))"
)


def test_spawn_streams_when_someone_is_listening(tmp_path: Path) -> None:
    events: list[dict] = []

    done = _real_spawn(
        [sys.executable, "-c", _PRINTS_TWO_EVENTS], cwd=tmp_path, on_event=events.append
    )

    assert done.returncode == 0
    assert [event["type"] for event in events] == ["system", "result"]


def test_spawn_runs_to_completion_when_nobody_is_listening(tmp_path: Path) -> None:
    done = _real_spawn([sys.executable, "-c", _PRINTS_TWO_EVENTS], cwd=tmp_path)

    assert done.returncode == 0
    assert final_text(done.stdout) == "ok"
