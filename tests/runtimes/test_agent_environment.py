"""`AgentRequest.environment` is the whole environment an agent starts with (spec:
acceptance-server-runs-in-the-scratch-environment, group 1): given, the agent sees it and
nothing of the test process; not given, it sees the process's as before.

The ACP agent is the real subprocess of `acp_agent.py`, which records the variables it
started with and lists its session only while one of them is set; the Claude runtime is its
own `spawn` running a harmless program, and an injected `execute` that records what it is
given.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.acp import AcpRuntime
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime, spawn
from tests.runtimes.acp_agent import ENVIRONMENT, SESSION, requests, use_agent
from tests.runtimes.claude_cli import finished_build

GIVEN = "ABK_TEST_GIVEN"
ONLY_HERE = "ABK_TEST_ONLY_IN_THE_PROCESS"
ADDED = "ABK_TEST_ADDED"
WATCHED = (GIVEN, ONLY_HERE, ADDED, "PYTEST_CURRENT_TEST")


def scratch(**extra: str) -> dict[str, str]:
    """A whole environment: enough to start a program, and what a test names."""
    return {"PATH": os.environ["PATH"], **extra}


@pytest.fixture(autouse=True)
def process_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ONLY_HERE, "from-the-process")
    monkeypatch.delenv(GIVEN, raising=False)
    monkeypatch.delenv(ADDED, raising=False)


def started_with(tmp_path: Path, **request: Any) -> dict[str, str | None]:
    record = tmp_path / "record.jsonl"
    use_agent(record, watch=WATCHED)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    result = AcpRuntime().run(
        AgentRequest(prompt="Implement group 1.", role="implement", cwd=worktree, **request)
    )
    assert result.ok, result.error
    (seen,) = requests(record, ENVIRONMENT)
    return seen


def test_an_agent_given_an_environment_sees_it_and_not_the_test_process(tmp_path: Path) -> None:
    seen = started_with(tmp_path, environment=scratch(**{GIVEN: "given"}))

    assert seen[GIVEN] == "given"
    assert seen["PYTEST_CURRENT_TEST"] is None
    assert seen[ONLY_HERE] is None


def test_an_agent_given_none_sees_the_process_environment(tmp_path: Path) -> None:
    seen = started_with(tmp_path, environment=None)

    assert seen[GIVEN] is None
    assert seen[ONLY_HERE] == "from-the-process"
    assert seen["PYTEST_CURRENT_TEST"]


def test_the_request_env_is_added_on_top_of_the_given_environment(tmp_path: Path) -> None:
    seen = started_with(tmp_path, environment=scratch(**{GIVEN: "given"}), env={ADDED: "added"})

    assert (seen[GIVEN], seen[ADDED]) == ("given", "added")
    assert seen[ONLY_HERE] is None
    assert seen["PYTEST_CURRENT_TEST"] is None


def lists_session_only_with(tmp_path: Path) -> AcpRuntime:
    """An agent that resumes and lists `SESSION` only while `GIVEN` is set in its environment."""
    use_agent(
        tmp_path / "record.jsonl",
        resume=True,
        list_sessions=True,
        sessions=(SESSION,),
        sessions_when=GIVEN,
    )
    return AcpRuntime()


def test_the_resume_check_starts_the_agent_in_the_given_environment(tmp_path: Path) -> None:
    runtime = lists_session_only_with(tmp_path)

    assert runtime.can_resume_session(SESSION, tmp_path, environment=scratch(**{GIVEN: "1"}))
    assert not runtime.can_resume_session(SESSION, tmp_path, environment=scratch())


def test_a_yes_in_one_environment_is_not_reused_for_another(tmp_path: Path) -> None:
    runtime = lists_session_only_with(tmp_path)
    assert runtime.can_resume_session(SESSION, tmp_path, environment=scratch(**{GIVEN: "1"}))

    assert not runtime.can_resume_session(SESSION, tmp_path, environment=scratch())
    assert not runtime.can_resume_session(SESSION, tmp_path)


def test_a_resume_check_with_no_environment_takes_the_process_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = lists_session_only_with(tmp_path)
    assert not runtime.can_resume_session(SESSION, tmp_path)

    monkeypatch.setenv(GIVEN, "1")

    assert runtime.can_resume_session(SESSION, tmp_path)


PROGRAM = ["sh", "-c", 'printf %s "$ABK_TEST_GIVEN:$ABK_TEST_ADDED:$ABK_TEST_ONLY_IN_THE_PROCESS"']


@pytest.mark.parametrize("streamed", [False, True], ids=["captured", "streamed"])
def test_spawn_runs_the_program_in_the_given_environment(streamed: bool) -> None:
    result = spawn(
        PROGRAM,
        environment=scratch(**{GIVEN: "given"}),
        on_event=(lambda event: None) if streamed else None,
    )

    assert result.stdout == "given::"


@pytest.mark.parametrize("streamed", [False, True], ids=["captured", "streamed"])
def test_spawn_adds_env_on_top_of_the_given_environment(streamed: bool) -> None:
    result = spawn(
        PROGRAM,
        env={ADDED: "added"},
        environment=scratch(**{GIVEN: "given"}),
        on_event=(lambda event: None) if streamed else None,
    )

    assert result.stdout == "given:added:"


def test_spawn_with_no_environment_runs_in_the_process_environment() -> None:
    assert spawn(PROGRAM).stdout == "::from-the-process"


def run_claude(tmp_path: Path, execute: Any, **request: Any) -> None:
    result = ClaudeCodeRuntime(execute=execute).run(
        AgentRequest(prompt="Go.", role="implement", cwd=tmp_path, **request)
    )
    assert result.ok, result.error


def test_the_runtime_hands_the_environment_to_execute_only_when_set(tmp_path: Path) -> None:
    seen: list[dict[str, Any]] = []

    def execute(
        argv: list[str], *, cwd: Path | None = None, on_event=None, input=None, **extra: Any
    ):
        seen.append(extra)
        return subprocess.CompletedProcess(argv, 0, finished_build(tmp_path, "done"), "")

    run_claude(tmp_path, execute)
    run_claude(tmp_path, execute, environment={"PATH": "/bin"})
    run_claude(tmp_path, execute, env={ADDED: "x"}, environment={"PATH": "/bin"})

    assert seen == [
        {},
        {"environment": {"PATH": "/bin"}},
        {"env": {ADDED: "x"}, "environment": {"PATH": "/bin"}},
    ]


def test_an_execute_written_without_the_argument_still_works(tmp_path: Path) -> None:
    def execute(argv: list[str], *, cwd: Path | None = None, on_event=None, input=None):
        return subprocess.CompletedProcess(argv, 0, finished_build(tmp_path, "done"), "")

    run_claude(tmp_path, execute)
