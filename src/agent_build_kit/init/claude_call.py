"""The init steps' older injection point: a `claude -p` call that hands back
its text.

Research and propose reach their agent through the runtime seam. A caller
may still pass a `RunClaude` instead, which is then what the Claude Code
adapter runs its argv through — so a test sees the exact argv, and nothing
in this package calls the real binary during one.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable

from agent_build_kit import runtimes
from agent_build_kit.runtimes import AgentResult, AgentRuntime
from agent_build_kit.runtimes.claude_code import through

# (argv, *, cwd=None) -> the model's text output.
RunClaude = Callable[..., str]


def runtime_for(run_claude: RunClaude | None, runtime: AgentRuntime | None) -> AgentRuntime:
    """The runtime a step runs on: the one it was given, else Claude Code over
    the given `RunClaude`, else the active one."""
    if runtime is not None:
        return runtime
    if run_claude is None:
        return runtimes.active()

    def run(argv: list[str], *, cwd=None) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, run_claude(argv, cwd=cwd), "")

    return through(run)


def succeeded(result: AgentResult) -> str:
    """The run's answer, or the error a failed run ended on — never whatever
    text it left behind."""
    if not result.ok:
        raise RuntimeError(result.error)
    return result.text
