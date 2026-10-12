"""A planner whose model call ends on an outage, and the clock and probe around it.

The runtime stand-in raises the typed errors the adapters raise from inside `run`, so the
error reaches `plan_all` as it does from a real runtime; the probe is replaced at the seam
the step handler reads it through.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from agent_build_kit.runtimes import AgentRequest, NetworkUnavailable, ServiceUnavailable
from tests.pipeline.test_network_outage_parking import outage
from tests.pipeline.test_service_outage_parking import overloaded

MINUTE = timedelta(minutes=1)


def network(strength: str = "strong") -> NetworkUnavailable:
    """The unit-parking tests' network error, strong unless said otherwise."""
    return outage(strength)


def service(status: int = 529) -> ServiceUnavailable:
    return overloaded(status)


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
