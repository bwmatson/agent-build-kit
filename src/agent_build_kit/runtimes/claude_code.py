"""Claude Code as an agent runtime: `claude -p`, run as a subprocess."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from agent_build_kit.pipeline.usage_guard import UsageReading
from agent_build_kit.runtimes.base import (
    AgentRequest,
    AgentResult,
    PolicyCoverage,
    PolicyReport,
    UsageStatus,
)

# (argv, *, cwd, on_event) -> the finished process: `claude_stream.stream_run`'s
# shape. `on_event` is called with each JSON event as it is printed, and is
# None for a run that is not streamed.
Execute = Callable[..., subprocess.CompletedProcess[str]]

# A usage reading, or None when there is none: `usage_guard`'s readers.
ReadUsage = Callable[[], UsageReading | None]


class ClaudeCodeRuntime:
    name: str
    implemented: bool
    policy_coverage: PolicyCoverage
    supports_usage_tracking: bool
    supports_streaming: bool

    def __init__(
        self,
        *,
        execute: Execute | None = None,
        read_live: ReadUsage | None = None,
        read_cached: ReadUsage | None = None,
    ) -> None:
        raise NotImplementedError

    def run(self, request: AgentRequest) -> AgentResult:
        raise NotImplementedError

    def get_usage_status(self) -> UsageStatus | None:
        raise NotImplementedError

    def check_policy(self, cwd: Path) -> PolicyReport:
        raise NotImplementedError
