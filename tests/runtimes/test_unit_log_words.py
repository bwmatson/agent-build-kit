"""What an agent run hands the unit's log and what it hands the journal.

The journal gets each reply and command as one clipped line; the unit's log
gets them whole, line breaks kept. The `claude` process is faked at its
stream-json boundary and the ACP agent is a real subprocess over stdio.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.acp import AcpRuntime
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.runtimes.acp_agent import use_agent
from tests.runtimes.claude_cli import FakeClaude, finished_build, stream

REPLY = (
    "First I will read the spec and the tests that pin it.\n"
    "\n"
    "Then I will add the marker to the app module, " + "and say why " * 30 + "\n"
    "\n"
    "    def indented() -> None: ...\n"
    "Last, I will run the checks."
)
COMMAND = "uv run pytest tests/test_app.py \\\n  -k marker \\\n  -x --no-header " + "-q " * 80


class Heard:
    """The two callbacks of a request, and what each was told."""

    def __init__(self) -> None:
        self.journal: list[str] = []
        self.unit_log: list[str] = []

    def request(self, cwd: Path) -> AgentRequest:
        return AgentRequest(
            prompt="Implement group 1 of add-marker.",
            role="implement",
            cwd=cwd,
            on_event=self.journal.append,
            on_transcript=self.unit_log.append,
        )


def starting(lines: list[str], word: str) -> list[str]:
    return [line for line in lines if line.strip().startswith(word)]


def assert_reply_whole_in_unit_log_clipped_in_journal(heard: Heard) -> None:
    (whole,) = [line for line in starting(heard.unit_log, "says:") if "First I will" in line]
    assert whole.strip() == f"says: {REPLY}"
    (clipped,) = [line for line in starting(heard.journal, "says:") if "First I will" in line]
    assert "\n" not in clipped
    assert clipped.strip().startswith("says: First I will read the spec")
    assert len(clipped) < len(whole)


def test_a_claude_reply_is_whole_in_the_unit_log_and_one_clipped_line_in_the_journal(
    tmp_path: Path,
) -> None:
    heard = Heard()
    fake = FakeClaude(stdout=finished_build(tmp_path, REPLY))

    ClaudeCodeRuntime(execute=fake).run(heard.request(tmp_path))

    assert_reply_whole_in_unit_log_clipped_in_journal(heard)


def test_a_claude_command_is_whole_in_the_unit_log_and_one_clipped_line_in_the_journal(
    tmp_path: Path,
) -> None:
    opening = finished_build(tmp_path, "done").splitlines()[0]
    call = {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_01AbCdEfGhJkLmNpQrStUvWx",
                    "name": "Bash",
                    "input": {"command": COMMAND, "description": "Run the marker test"},
                }
            ],
        },
    }
    heard = Heard()
    fake = FakeClaude(stdout=opening + "\n" + stream(call))

    ClaudeCodeRuntime(execute=fake).run(heard.request(tmp_path))

    (whole,) = starting(heard.unit_log, "Bash")
    assert whole.strip() == f"Bash {COMMAND}"
    (clipped,) = starting(heard.journal, "Bash")
    assert "\n" not in clipped
    assert len(clipped) < len(whole)


def test_the_pipelines_lines_in_a_claude_run_reach_the_unit_log_as_the_journal_has_them(
    tmp_path: Path,
) -> None:
    heard = Heard()
    fake = FakeClaude(stdout=finished_build(tmp_path, "done"))

    ClaudeCodeRuntime(execute=fake).run(heard.request(tmp_path))

    assert starting(heard.journal, "claude started"), "the journal still gets its lines"
    assert starting(heard.unit_log, "claude started") == starting(heard.journal, "claude started")


def test_an_acp_reply_is_whole_in_the_unit_log_and_one_clipped_line_in_the_journal(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "worktree"
    (worktree / "src").mkdir(parents=True)
    (worktree / "src" / "app.py").write_text("MARKER = None\n")
    use_agent(tmp_path / "agent.jsonl", reply=REPLY)
    heard = Heard()

    result = AcpRuntime().run(heard.request(worktree))

    assert result.ok is True
    assert_reply_whole_in_unit_log_clipped_in_journal(heard)
