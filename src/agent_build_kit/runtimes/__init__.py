"""The agent runtimes a workspace can name in abk.yaml."""

from __future__ import annotations

from agent_build_kit.runtimes import known_agents
from agent_build_kit.runtimes.base import (
    AgentInterrupted,
    AgentRateLimited,
    AgentRequest,
    AgentResult,
    AgentRuntime,
    Candidate,
    NetworkUnavailable,
    PolicyReport,
    Run,
    ServiceUnavailable,
    ToolPolicy,
    UsageStatus,
    Which,
    candidates_of,
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


def candidates(which: Which, run: Run) -> list[Candidate]:
    """What every runtime finds on this machine, with no model call. The known protocol
    agents are listed even where the protocol runtime is not registered for want of its
    extra, each unusable with that reason, so the person learns what installing it adds."""
    found = [c for name in names() for c in candidates_of(get(name), which, run)]
    if known_agents.RUNTIME_NAME not in names():
        found += known_agents.probe(which, run)
    return found


def _load_builtin() -> None:
    if _REGISTRY:
        return
    from agent_build_kit.runtimes import claude_code

    register(claude_code.RUNTIME)
    # Only with the `acp` extra installed: an installation without it imports
    # cleanly and does not see the runtime.
    try:
        from agent_build_kit.runtimes import acp
    except ModuleNotFoundError as exc:
        # Only the library's absence; a failure of acp.py's own imports is a
        # defect to surface, not a runtime to hide.
        if exc.name is None or not (exc.name == "acp" or exc.name.startswith("acp.")):
            raise
    else:
        register(acp.RUNTIME)


__all__ = [
    "AgentInterrupted",
    "AgentRateLimited",
    "NetworkUnavailable",
    "ServiceUnavailable",
    "AgentRequest",
    "AgentResult",
    "AgentRuntime",
    "PolicyReport",
    "ToolPolicy",
    "UsageStatus",
    "active",
    "candidates",
    "get",
    "names",
    "register",
]
