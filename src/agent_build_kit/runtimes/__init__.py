"""The agent runtimes a workspace can name in abk.yaml."""

from __future__ import annotations

from agent_build_kit.runtimes.base import (
    AgentInterrupted,
    AgentRateLimited,
    AgentRequest,
    AgentResult,
    AgentRuntime,
    PolicyReport,
    ToolPolicy,
    UsageStatus,
)

_REGISTRY: dict[str, AgentRuntime] = {}


def register(runtime: AgentRuntime) -> None:
    raise NotImplementedError


def get(name: str) -> AgentRuntime:
    raise NotImplementedError


def names() -> list[str]:
    raise NotImplementedError


def _load_builtin() -> None:
    raise NotImplementedError


__all__ = [
    "AgentInterrupted",
    "AgentRateLimited",
    "AgentRequest",
    "AgentResult",
    "AgentRuntime",
    "PolicyReport",
    "ToolPolicy",
    "UsageStatus",
    "get",
    "names",
    "register",
]
