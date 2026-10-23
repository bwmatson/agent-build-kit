"""A runtime a workspace can select by name, for the setup checks.

Where `stand_in.StandInRuntime` is handed to one call site, this one is put in
the registry, so that `abk.yaml`'s `runtime:` or `ABK_RUNTIME` can name it, and
it says what `doctor` and `init` ask of a runtime: whether it is implemented,
how much it interposes on, which facts it cannot run without, and — in turn,
one answer per `check_policy` call — which forbidden classes it refuses.
"""

from __future__ import annotations

from collections.abc import Collection
from pathlib import Path

import pytest

from agent_build_kit import runtimes
from agent_build_kit.config import ModelsConfig
from agent_build_kit.pipeline.command_spellings import SpellingName, probe_rows
from agent_build_kit.runtimes import AgentRequest, AgentResult, AgentRuntime, PolicyReport
from agent_build_kit.runtimes.base import PolicyCoverage, PromptTransport, SpellingResult
from agent_build_kit.sandboxes import Coverage


class SelectableRuntime:
    policy_check_prompts_agent: bool = False
    sandbox_note: str = ""
    supports_usage_tracking: bool = False
    supports_streaming: bool = False
    supports_session_resume: bool = False
    passes_env: bool = False
    prompt_transport: PromptTransport = PromptTransport.PROTOCOL

    def __init__(
        self,
        name: str,
        *,
        implemented: bool = True,
        policy_coverage: PolicyCoverage = "all_calls",
        sandbox_coverage: Coverage = Coverage.PROCESS,
        requires: tuple[str, ...] = (),
        reports: tuple[PolicyReport, ...] = (PolicyReport(ok=True),),
        log: list[str] | None = None,
        agent_command: tuple[str, ...] = (),
        default_models: ModelsConfig | None = None,
    ) -> None:
        self.name = name
        self.implemented = implemented
        self.policy_coverage: PolicyCoverage = policy_coverage
        self.sandbox_coverage = sandbox_coverage
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


def select[R: AgentRuntime](monkeypatch: pytest.MonkeyPatch, runtime: R) -> R:
    """Register `runtime` for one test. The built-in runtimes are loaded
    first: the registry fills itself only while it is empty."""
    runtimes.names()
    monkeypatch.setitem(runtimes._REGISTRY, runtime.name, runtime)
    return runtime


_: AgentRuntime = SelectableRuntime("typed")

AMEND = "amending a commit"
OPEN_SPELLING = SpellingName.DIRECTORY


def spelling_report(
    *, refused: bool = False, open_rows: Collection[tuple[str, SpellingName]] | None = None
) -> PolicyReport:
    """What the probe reports for the whole table: a result per probe row, in
    table order. Every row is refused but the `open_rows` (class, spelling), which
    are run without asking: by default the amend's `-C` spelling, none when `refused`."""
    if open_rows is None:
        open_rows = set() if refused else {(AMEND, OPEN_SPELLING)}
    results = tuple(
        SpellingResult(
            label=label,
            spelling=spelling.name.value,
            command=spelling.command,
            refused=(label, spelling.name) not in open_rows,
        )
        for label, spelling in probe_rows()
    )
    unenforced = tuple(
        result.label
        if result.spelling == SpellingName.PLAIN
        else f"{result.label} (as {result.command})"
        for result in results
        if not result.refused
    )
    return PolicyReport(ok=not unenforced, unenforced=unenforced, results=results)


def amend_finding() -> str:
    """The rendering of `spelling_report()` that `describe` owes: the amend
    class alone, its open spelling first and the others after, in table order."""
    rows = [(s.name, s.command) for label, s in probe_rows() if label == AMEND]
    open_ = [f"`{c}`" for n, c in rows if n == OPEN_SPELLING]
    shut = [f"`{c}`" for n, c in rows if n != OPEN_SPELLING]
    return f"{AMEND}: not refused as {', '.join(open_)}; refused as {', '.join(shut)}"
