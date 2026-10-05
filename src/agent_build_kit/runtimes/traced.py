"""An agent call as a span, and what it measures (spec: telemetry).

Every runtime's `run` goes through `traced`, so the agent span and the turn and
token metrics are the same whichever engine answered. What is recorded is
counts and names; never the prompt, the answer or an error's text.
"""

from __future__ import annotations

from collections.abc import Callable

from agent_build_kit import telemetry
from agent_build_kit.runtimes.base import (
    AgentInterrupted,
    AgentRateLimited,
    AgentRequest,
    AgentResult,
)

# A review by the rework model is still a review: the model attribute says
# which model judged it.
ROLES = {"rework_review": "review"}


def traced(runtime: str, request: AgentRequest, call: Callable[[], AgentResult]) -> AgentResult:
    """`call()` inside an `agent` span below whatever span is current."""
    role = ROLES.get(request.role, request.role)
    model = request.model or "default"
    with telemetry.tracer().start_as_current_span(
        "agent", attributes={"runtime": runtime, "model": model, "role": role}
    ) as span:
        outcome = "failed"
        try:
            result = call()
        except AgentInterrupted:
            outcome = "interrupted"
            raise
        except AgentRateLimited:
            outcome = "rate_limited"
            raise
        else:
            # A run that exits cleanly can still close on an error result
            # (`error_max_turns`): the span says so, as the caller reads the text.
            outcome = "ok" if result.ok and not result.stop_reason.startswith("error") else "failed"
            if result.turns is not None:
                span.set_attribute("turns", result.turns)
                telemetry.observe("abk.agent.turns", result.turns, role=role, model=model)
            for kind, tokens in result.tokens.items():
                telemetry.count("abk.agent.tokens", tokens, role=role, model=model, kind=kind)
            return result
        finally:
            span.set_attribute("outcome", outcome)
