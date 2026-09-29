"""What an agent execution engine has to answer, and the values it answers
with.

Every "run the agent and get a result" call in the pipeline goes through one
`AgentRuntime.run()`, given an `AgentRequest` built from abk-level concepts (a
role, a working directory, a tool policy) rather than one runtime's CLI flags.

Stub: the value objects declare their fields only; see docs/agent-runtimes.md.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel

PermissionMode = Literal["edit", "read_only"]

Role = Literal["implement", "rework", "review", "rework_review", "generic"]

PolicyCoverage = Literal["all_calls", "agent_flagged", "none"]


class ToolPolicy(BaseModel):
    specs_dir: Path | None = None
    branch_prefix: str = "spec/"


class AgentRequest(BaseModel):
    prompt: str
    role: Role = "generic"
    cwd: Path | None = None
    add_dirs: tuple[Path, ...] = ()
    model: str | None = None
    allowed_tools: str = ""
    denied_tools: str = ""
    permission_mode: PermissionMode = "edit"
    policy: ToolPolicy | None = None
    on_event: Callable[[str], None] | None = None


class AgentResult(BaseModel):
    ok: bool
    text: str
    raw: str = ""
    error: str = ""
    stop_reason: str = ""


class PolicyReport(BaseModel):
    ok: bool
    unenforced: tuple[str, ...] = ()
    fix: str = ""


class AgentInterrupted(RuntimeError):
    pass


class AgentRateLimited(RuntimeError):
    def __init__(self, message: str, *, resets_at: datetime | None = None) -> None:
        raise NotImplementedError


class UsageStatus(BaseModel):
    session_pct: int
    weekly_pct: int
    resets_at: datetime | None
    source: str


class AgentRuntime(Protocol):
    name: str
    implemented: bool
    policy_coverage: PolicyCoverage
    supports_usage_tracking: bool
    supports_streaming: bool

    def run(self, request: AgentRequest) -> AgentResult: ...

    def get_usage_status(self) -> UsageStatus | None: ...

    def check_policy(self, cwd: Path) -> PolicyReport: ...
