"""Agents that report what a run spent as a running total, for the tests of what the
ledger records of a call's cost.

`Metered` is the real Claude Code runtime's `claude` process, faked at its boundary: each
call prints the stream a real run does, with the next of `totals` as the result's
`total_cost_usd`. `Cumulative` is a runtime behind the seam that reports a session's
running total the way the ACP runtime does, optionally spending through a gateway key.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from agent_build_kit.pipeline.gateway_usage import KEY_ENV
from agent_build_kit.runtimes import AgentRequest, AgentResult
from tests.fake_gateway import FakeGateway
from tests.runner_fakes import Killed
from tests.runtimes.claude_cli import SESSION, FakeClaude, finished_build
from tests.runtimes.stand_in import StandInRuntime

BUILD_SESSION = "7e1c5a30-2b4d-4f86-a3c9-d0e8b6f21a47"


class Metered(FakeClaude):
    """A `claude` whose build calls all run in one session and report the next running
    total of `totals`. The call numbered `die_on` (from 1) announces its session and then
    dies, as a power loss does, and reports nothing. The call numbered `limited_on` reports its
    total and then exits on the usage limit."""

    def __init__(self, totals: Sequence[float], *, die_on: int = 0, limited_on: int = 0) -> None:
        super().__init__()
        self.totals = list(totals)
        self.die_on = die_on
        self.limited_on = limited_on
        self.count = 0
        self.reported = 0

    def __call__(
        self,
        argv: list[str],
        *,
        cwd: Path | None = None,
        on_event: Callable[[dict], None] | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.count += 1
        *events, closing = (
            finished_build(cwd or Path("."), "done").replace(SESSION, BUILD_SESSION).splitlines()
        )
        if self.count == self.die_on:
            if on_event is not None:
                on_event(json.loads(events[0]))
            raise Killed("power loss")
        ended = json.loads(closing) | {"total_cost_usd": self.totals[self.reported]}
        self.reported += 1
        limited = self.count == self.limited_on
        self.returncode = 1 if limited else 0
        self.stderr = "Claude AI usage limit reached|1900000000" if limited else ""
        self.stdout = "\n".join([*events, json.dumps(ended)]) + "\n"
        return super().__call__(argv, cwd=cwd, on_event=on_event, env=env)


class Cumulative(StandInRuntime):
    """A runtime that continues one session and reports the session's running total after
    each call (`totals`), as the ACP runtime does. With a gateway, call n also spends 0.5n
    through the key it was given."""

    name = "cumulative"
    supports_session_resume = True
    passes_env = True

    def __init__(
        self,
        totals: Sequence[float],
        gateway: FakeGateway | None = None,
        *,
        die_on: int = 0,
        own: Sequence[float] = (),
    ) -> None:
        super().__init__(answer="done")
        self.totals = list(totals)
        # What the runtime worked out as each call's own spend, as the ACP runtime does against
        # the total its agent replayed when the session was loaded; none when not given.
        self.own = list(own)
        self.gateway = gateway
        self.die_on = die_on

    def run(self, request: AgentRequest) -> AgentResult:
        self.requests.append(request)
        n = len(self.requests)
        key = request.env.get(KEY_ENV)
        if key and self.gateway is not None:
            self.gateway.spend(key, prompt=1000 * n, completion=100 * n, cost=0.5 * n)
        session = request.resume_session or "cumulative-session"
        if request.on_session:
            request.on_session(session)
        if n == self.die_on:
            raise Killed("power loss")
        result = AgentResult(
            ok=True,
            text="done",
            session_id=session,
            cost_usd=self.own[n - 1] if self.own else None,
            cumulative_cost_usd=self.totals[n - 1],
            usage_source="reported",
        )
        if request.on_result:
            request.on_result(result)
        return result
