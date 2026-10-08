"""`AgentRequest.env` reaches the `claude` process (spec: command-output-to-files).

The scratch folder's path, `ABK_OUT`, travels in the request's environment, so
the default runtime has to put it in what `claude` is started with, on top of
the process's own environment.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime, spawn
from tests.runtimes.claude_cli import FakeClaude, finished_build

ARGV = ["sh", "-c", 'printf %s "$ABK_OUT:$ABK_SPAWN_PROBE"']


def test_the_request_environment_reaches_the_claude_process(tmp_path: Path) -> None:
    fake = FakeClaude(stdout=finished_build(tmp_path, "done"))

    ClaudeCodeRuntime(execute=fake).run(
        AgentRequest(prompt="Go.", role="implement", cwd=tmp_path, env={"ABK_OUT": "/x"})
    )

    assert fake.envs[0] is not None
    assert fake.envs[0]["ABK_OUT"] == "/x"


@pytest.mark.parametrize("streamed", [False, True], ids=["captured", "streamed"])
def test_spawn_adds_the_environment_to_its_own(
    streamed: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ABK_SPAWN_PROBE", "kept")
    events: list[dict] = []

    result = spawn(ARGV, env={"ABK_OUT": "/x"}, on_event=events.append if streamed else None)

    assert result.stdout == "/x:kept"
