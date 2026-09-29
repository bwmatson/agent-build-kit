"""An agent speaking the Agent Client Protocol, as an agent runtime.

Spawns the agent `runtimes.acp.command` names and drives one session per run
over stdio, on its own event loop so callers stay synchronous.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.config import ModelsConfig
from agent_build_kit.runtimes.base import (
    AgentRequest,
    AgentResult,
    AgentRuntime,
    PolicyCoverage,
    PolicyReport,
)

NAME = "acp"


class AcpRuntime:
    name: str = NAME
    implemented: bool = False
    policy_coverage: PolicyCoverage = "agent_flagged"
    supports_usage_tracking: bool = False
    supports_streaming: bool = True
    # There is no default agent to spawn.
    requires: tuple[str, ...] = ("command",)
    agent_command: tuple[str, ...] = ()
    default_models: ModelsConfig = ModelsConfig()

    def run(self, request: AgentRequest) -> AgentResult:
        raise NotImplementedError

    def get_usage_status(self) -> None:
        raise NotImplementedError

    def check_policy(self, cwd: Path) -> PolicyReport:
        raise NotImplementedError


RUNTIME = AcpRuntime()

_: AgentRuntime = RUNTIME
