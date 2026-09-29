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

# What a workspace runs on when abk.yaml and the machine name no other.
DEFAULT = "claude_code"


def register(runtime: AgentRuntime) -> None:
    _REGISTRY[runtime.name] = runtime


def get(name: str) -> AgentRuntime:
    _load_builtin()
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown agent runtime {name!r} (known: {', '.join(names())})") from None


def active() -> AgentRuntime:
    """The runtime a call site uses unless it is given one. Resolved per
    call, never captured at import: this machine's `ABK_RUNTIME`, then the
    active workspace's `runtime:`."""
    from agent_build_kit import config

    return get(config.runtime_name())


def names() -> list[str]:
    _load_builtin()
    return sorted(_REGISTRY)


def _load_builtin() -> None:
    if _REGISTRY:
        return
    from agent_build_kit.runtimes import claude_code

    register(claude_code.RUNTIME)


__all__ = [
    "AgentInterrupted",
    "AgentRateLimited",
    "AgentRequest",
    "AgentResult",
    "AgentRuntime",
    "PolicyReport",
    "ToolPolicy",
    "UsageStatus",
    "active",
    "get",
    "names",
    "register",
]
