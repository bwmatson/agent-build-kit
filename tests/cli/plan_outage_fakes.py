"""A planner whose model call ends on an outage, and the clock and probe around it.

The runtime stand-in raises the typed errors the adapters raise from inside `run`, so the
error reaches `plan_all` as it does from a real runtime; the probe is replaced at the seam
the step handler reads it through.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from agent_build_kit.runtimes import AgentRequest, NetworkUnavailable, ServiceUnavailable

API = "api.example.test"
WORDS = "API Error: Can't reach the API server — check your internet or DNS (EAI_AGAIN)"
MINUTE = timedelta(minutes=1)


def network(strength: str = "strong") -> NetworkUnavailable:
    return NetworkUnavailable(WORDS, strength=strength, host=API)  # type: ignore[arg-type]


def service(status: int = 529) -> ServiceUnavailable:
    return ServiceUnavailable(f"API Error: {status} Overloaded", status=status)


def raises(error: Exception) -> Callable[[AgentRequest], None]:
    """What a runtime stand-in does when asked: fail with `error`."""

    def act(request: AgentRequest) -> None:
        raise error

    return act


def moment(text: str) -> datetime:
    return datetime.fromisoformat(text)


def clock_time(text: str) -> str:
    """How a stored time reads in a line printed for a person: local, to the minute."""
    return f"{moment(text).astimezone():%H:%M}"
