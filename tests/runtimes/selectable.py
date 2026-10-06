"""A runtime a workspace can select by name, for the setup checks.

Where `stand_in.StandInRuntime` is handed to one call site, this one is put in
the registry, so that `abk.yaml`'s `runtime:` or `ABK_RUNTIME` can name it, and
it says what `doctor` and `init` ask of a runtime: whether it is implemented,
how much it interposes on, which facts it cannot run without, and — in turn,
one answer per `check_policy` call — which forbidden classes it refuses.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import runtimes
from agent_build_kit.config import ModelsConfig
from agent_build_kit.runtimes import AgentRequest, AgentResult, AgentRuntime, PolicyReport
from agent_build_kit.runtimes.base import PolicyCoverage


class SelectableRuntime:
    supports_usage_tracking: bool = False
    supports_streaming: bool = False
    supports_session_resume: bool = False
    passes_env: bool = False

    def __init__(
        self,
        name: str,
        *,
        implemented: bool = True,
        policy_coverage: PolicyCoverage = "all_calls",
        requires: tuple[str, ...] = (),
        reports: tuple[PolicyReport, ...] = (PolicyReport(ok=True),),
        log: list[str] | None = None,
        agent_command: tuple[str, ...] = (),
        default_models: ModelsConfig | None = None,
    ) -> None:
        self.name = name
        self.implemented = implemented
        self.policy_coverage: PolicyCoverage = policy_coverage
        self.requires = requires
        self.agent_command = agent_command
        self.default_models = default_models or ModelsConfig()
        self.reports = reports
        self.log = log if log is not None else []
        self.checked: list[Path] = []

    def run(self, request: AgentRequest) -> AgentResult:
        raise AssertionError("a setup check ran an agent")

    def get_usage_status(self) -> None:
        return None

    def check_policy(self, cwd: Path) -> PolicyReport:
        self.checked.append(cwd)
        self.log.append("check")
        # The last answer repeats once the list runs out.
        return self.reports[min(len(self.checked), len(self.reports)) - 1]


def select(monkeypatch: pytest.MonkeyPatch, runtime: SelectableRuntime) -> SelectableRuntime:
    """Register `runtime` for one test. The built-in runtimes are loaded
    first: the registry fills itself only while it is empty."""
    runtimes.names()
    monkeypatch.setitem(runtimes._REGISTRY, runtime.name, runtime)
    return runtime


_: AgentRuntime = SelectableRuntime("typed")
