"""The one writer of an agent call's row in the usage ledger."""

from __future__ import annotations

from collections.abc import Callable

from agent_build_kit.pipeline.gateway_usage import Spend
from agent_build_kit.runtimes import AgentRequest, AgentRuntime


def call_recorder(
    node: str,
    *,
    unit: str = "",
    change: str = "",
    repo: str = "",
    tier: str = "",
    round: int = 0,
    resumed: bool = False,
    say: Callable[[str], None],
    gateway: Callable[[], Spend] | None = None,
) -> Callable[..., None]:
    """What a runtime calls with the finished `AgentResult`, as
    `record(result, *, role, model, runtime, gateway=None)`."""
    raise NotImplementedError


def recorded(
    request: AgentRequest,
    runtime: AgentRuntime,
    *,
    node: str,
    unit: str = "",
    change: str = "",
    repo: str = "",
    tier: str = "",
    round: int = 0,
    resumed: bool = False,
    say: Callable[[str], None],
) -> AgentRequest:
    """`request` with `on_result` writing the call's row under `node`."""
    raise NotImplementedError
