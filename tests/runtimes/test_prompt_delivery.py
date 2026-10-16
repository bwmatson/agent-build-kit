"""The Claude Code runtime hands the prompt to the process on its standard input, whole and
unchanged, on the streamed path and the plain one (spec: prompt-delivery).

The process is a stand-in executable: a script that writes the arguments and the bytes it was
given on standard input to files and prints a result event, the shape `claude` prints.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from agent_build_kit import config
from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.runtimes import AgentRequest, claude_code
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime, build_argv

# Bound at import, before the suite's guard replaces `spawn` on the module.
real_spawn = claude_code.spawn

SCRIPT = """import json, pathlib, sys
here = pathlib.Path(__file__).parent
(here / "stdin.bin").write_bytes(sys.stdin.buffer.read())
(here / "args.json").write_text(json.dumps(sys.argv[1:]))
print(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                  "result": "the reply", "num_turns": 1}))
"""

NO_ATTRIBUTION = {"attribution": {"commit": "", "pr": ""}, "includeCoAuthoredBy": False}

# Two, three and one byte: 300,000 bytes in all, with non-ASCII text in it.
LARGE_PROMPT = "é✓a" * 50_000


class StandIn:
    """The executable `runtimes.claude_code.command` names, and what it was given."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        script = folder / "claude_stand_in.py"
        script.write_text(SCRIPT)
        entry = {"command": [sys.executable, str(script)]}
        config.activate(WorkspaceConfig.model_validate({"runtimes": {"claude_code": entry}}))

    @property
    def stdin(self) -> bytes:
        return (self.folder / "stdin.bin").read_bytes()

    @property
    def args(self) -> list[str]:
        return json.loads((self.folder / "args.json").read_text())


@pytest.fixture
def process(tmp_path: Path) -> StandIn:
    return StandIn(tmp_path)


def run(request: AgentRequest):
    return ClaudeCodeRuntime(execute=real_spawn).run(request)


def assert_delivered_on_stdin(process: StandIn, prompt: str) -> None:
    assert process.stdin == prompt.encode()
    assert "-p" in process.args
    assert prompt not in process.args
    assert all(len(arg) < 10_000 for arg in process.args), "a long argument holds the prompt"


def test_a_large_prompt_arrives_whole_on_standard_input(process: StandIn) -> None:
    result = run(AgentRequest(prompt=LARGE_PROMPT))

    assert result.ok
    assert result.text == "the reply"
    assert_delivered_on_stdin(process, LARGE_PROMPT)


def test_a_large_prompt_arrives_whole_on_the_streamed_path(process: StandIn) -> None:
    result = run(AgentRequest(prompt=LARGE_PROMPT, on_event=lambda line: None))

    assert result.text == "the reply"
    assert_delivered_on_stdin(process, LARGE_PROMPT)
    assert process.args[process.args.index("--output-format") + 1] == "stream-json"


def test_a_resumed_run_that_keeps_its_record_carries_a_large_prompt_the_same_way(
    process: StandIn,
) -> None:
    result = run(AgentRequest(prompt=LARGE_PROMPT, resume_session="abc", keep_record=True))

    assert result.text == "the reply"
    assert_delivered_on_stdin(process, LARGE_PROMPT)
    assert process.args[process.args.index("--resume") + 1] == "abc"


def test_a_resumed_streamed_run_carries_a_large_prompt_the_same_way(process: StandIn) -> None:
    result = run(
        AgentRequest(prompt=LARGE_PROMPT, resume_session="abc", on_event=lambda line: None)
    )

    assert result.text == "the reply"
    assert_delivered_on_stdin(process, LARGE_PROMPT)


def test_a_short_prompt_changes_nothing_but_where_it_travels(process: StandIn) -> None:
    request = AgentRequest(prompt="Say hello to the world now", model="haiku", allowed_tools="Read")

    result = run(request)

    assert (result.ok, result.text) == (True, "the reply")
    assert process.args == [
        "-p",
        "--settings",
        json.dumps(NO_ATTRIBUTION),
        "--allowedTools",
        "Read",
        "--permission-mode",
        "acceptEdits",
        "--model",
        "haiku",
        "--output-format",
        "text",
    ]
    assert build_argv(request)[-len(process.args) :] == process.args
    assert process.stdin == b"Say hello to the world now"


def test_a_prompt_of_a_hundred_bytes_is_delivered_on_standard_input_too(process: StandIn) -> None:
    prompt = "p" * 100

    run(AgentRequest(prompt=prompt))

    assert_delivered_on_stdin(process, prompt)
