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

from agent_build_kit.config import ModelsConfig
from agent_build_kit.runtimes import AgentRequest, AgentResult, AgentRuntime, PolicyReport
from agent_build_kit.runtimes.base import PolicyCoverage, PromptTransport
from agent_build_kit.sandboxes import Coverage


class StandInRuntime:
    name: str = "stand_in"
    implemented: bool = True
    policy_coverage: PolicyCoverage = "all_calls"
    sandbox_coverage: Coverage = Coverage.NONE
    sandbox_note: str = ""
    policy_check_prompts_agent: bool = False
    supports_usage_tracking: bool = False
    supports_streaming: bool = False
    supports_session_resume: bool = False
    passes_env: bool = False
    prompt_transport: PromptTransport = PromptTransport.PROTOCOL
    requires: tuple[str, ...] = ()
    agent_command: tuple[str, ...] = ()
    default_models: ModelsConfig = ModelsConfig()

    def __init__(
        self,
        *,
        answer: str = "",
        raw: str = "",
        ok: bool = True,
        error: str = "",
        act: Callable[[AgentRequest], None] | None = None,
        respond: Callable[[AgentRequest], str] | None = None,
    ) -> None:
        self.answer = answer
        self.raw = raw
        self.ok = ok
        self.error = error
        self.act = act
        # The answer chosen from the request itself, so calls that overlap cannot read each
        # other's: when set, it is used in place of `answer`.
        self.respond = respond
        self.requests: list[AgentRequest] = []

    def run(self, request: AgentRequest) -> AgentResult:
        self.requests.append(request)
        if self.act is not None:
            self.act(request)
        text = self.respond(request) if self.respond is not None else self.answer
        return AgentResult(ok=self.ok, text=text, raw=self.raw, error=self.error)

    def get_usage_status(self) -> None:
        return None

    def check_policy(self, cwd: Path) -> PolicyReport:
        return PolicyReport(ok=True)

    @property
    def request(self) -> AgentRequest:
        assert len(self.requests) == 1, f"expected one agent run, got {len(self.requests)}"
        return self.requests[0]


class GrantsFolder(StandInRuntime):
    """A stand-in runtime that grants a folder for writing, as the Claude runtime grants the temp
    folder (`sandbox_paths`), so a policy built for it covers what lies inside that folder."""

    def __init__(self, folder: Path, **given: object) -> None:
        super().__init__(**given)  # type: ignore[arg-type]
        self.folder = folder

    def sandbox_paths(self, account: object = None) -> dict[str, list[str]]:
        return {"write": [str(self.folder)]}


_: AgentRuntime = StandInRuntime()
