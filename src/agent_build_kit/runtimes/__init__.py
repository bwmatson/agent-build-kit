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
    _REGISTRY[runtime.name] = runtime


def get(name: str) -> AgentRuntime:
    _load_builtin()
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown agent runtime {name!r} (known: {', '.join(names())})") from None


def names() -> list[str]:
    _load_builtin()
    return sorted(_REGISTRY)


def _load_builtin() -> None:
    if _REGISTRY:
        return
    from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime

    register(ClaudeCodeRuntime())


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
