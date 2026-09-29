"""An agent runtime that is not Claude Code: a plain class satisfying the
Protocol, as a second adapter or a test double would.

A call site given one proves it reaches the agent through the seam alone —
nothing it sends can be a `claude` flag, because nothing here reads one. What
it was asked is kept as the requests themselves; what it answers, and what it
does to the working directory meanwhile, the test decides.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from agent_build_kit.runtimes import AgentRequest, AgentResult, AgentRuntime, PolicyReport
from agent_build_kit.runtimes.base import PolicyCoverage


class StandInRuntime:
    name: str = "stand_in"
    implemented: bool = True
    policy_coverage: PolicyCoverage = "all_calls"
    supports_usage_tracking: bool = False
    supports_streaming: bool = False

    def __init__(
        self,
        *,
        answer: str = "",
        raw: str = "",
        ok: bool = True,
        error: str = "",
        act: Callable[[AgentRequest], None] | None = None,
    ) -> None:
        self.answer = answer
        self.raw = raw
        self.ok = ok
        self.error = error
        self.act = act
        self.requests: list[AgentRequest] = []

    def run(self, request: AgentRequest) -> AgentResult:
        self.requests.append(request)
        if self.act is not None:
            self.act(request)
        return AgentResult(ok=self.ok, text=self.answer, raw=self.raw, error=self.error)

    def get_usage_status(self) -> None:
        return None

    def check_policy(self, cwd: Path) -> PolicyReport:
        return PolicyReport(ok=True)

    @property
    def request(self) -> AgentRequest:
        assert len(self.requests) == 1, f"expected one agent run, got {len(self.requests)}"
        return self.requests[0]


_: AgentRuntime = StandInRuntime()
