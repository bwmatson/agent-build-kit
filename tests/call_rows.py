"""What a test needs to see the ledger row a call wrote: a runtime that reports what it spent,
as every runtime hands the finished result to the request's `on_result`, and the ledger read
back from disk."""

from __future__ import annotations

import json

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from agent_build_kit.runtimes import AgentRequest, AgentResult
from agent_build_kit.usage import Usage
from tests.runtimes.stand_in import StandInRuntime


class Spending(StandInRuntime):
    """A runtime whose every call reports tokens, cost and duration to `on_result`."""

    name = "spending"

    def run(self, request: AgentRequest) -> AgentResult:
        self.requests.append(request)
        if self.act is not None:
            self.act(request)
        result = AgentResult(
            ok=self.ok,
            text=self.answer,
            raw=self.raw,
            error=self.error,
            usage=Usage(input_tokens=1200, output_tokens=300),
            cost_usd=0.31,
            duration_ms=42_000,
            usage_source="reported",
        )
        if request.on_result:
            request.on_result(result)
        return result


def ledger_rows(installation: Installation) -> list[dict]:
    """Every line of the installation's usage ledger, as written."""
    path = installation.state_dir / LEDGER_NAME
    lines = path.read_text().splitlines() if path.exists() else []
    return [json.loads(line) for line in lines]


def agent_rows(installation: Installation) -> list[dict]:
    """The ledger's agent calls, not its spans."""
    return [row for row in ledger_rows(installation) if row.get("kind", "agent") == "agent"]
