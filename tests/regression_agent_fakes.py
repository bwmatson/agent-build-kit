"""The agent every test gets when it injects none, and the handlers' entry points over it.

The stand-in runtime, the change it writes and the OpenSpec stand-in are `regression_agent_support`
(shared with the tests of the agent itself). Here `DefaultAgent` is what the pipeline's handlers
run against when a test gives them no runtime: they then run the real agent step against it, and
`install` puts it behind the agent step's own runtime lookup.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agent_build_kit import openspec
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import regression_agent
from agent_build_kit.pipeline.flakes import Flake
from agent_build_kit.pipeline.regression_agent import FixKind, wait_on_regression
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.untouched_failures import PreExisting
from agent_build_kit.runtimes import AgentRequest, AgentRuntime
from tests.regression_agent_support import TEST, asked_kind, write_change
from tests.runtimes.stand_in import StandInRuntime


def validating(changes: Path):
    """A stand-in for `openspec validate` over the changes in `changes`: it refuses a change
    whose delta spec holds a requirement with no scenario, as the real one does."""

    def validate(argv, *, cwd, **kwargs) -> subprocess.CompletedProcess:
        items = []
        for change in sorted(p for p in changes.glob("*") if p.is_dir()):
            specs = [spec.read_text() for spec in change.glob("specs/*/spec.md")]
            valid = all("#### Scenario:" in text for text in specs)
            issues = [] if valid else [{"message": "a requirement has no scenario"}]
            items.append({"id": change.name, "valid": valid, "issues": issues})
        return subprocess.CompletedProcess(argv, 0, json.dumps({"items": items}), "")

    return validate


def waited_on(
    inst: Installation,
    failure: Flake,
    unit: StoredUnit,
    *,
    kind: FixKind = FixKind.FLAKY,
    wait: bool = True,
    runtime: AgentRuntime | None = None,
    **options: Any,
) -> str | None:
    """`wait_on_regression` as the handlers call it, with the default stand-in agent behind it
    unless `runtime` is given; `options` (a `clock`) go through."""
    return wait_on_regression(
        inst,
        failure,
        unit,
        kind=kind,
        runtime=runtime,
        wait=wait,
        say=lambda message: None,
        **options,
    )


def ensure_fix(inst: Installation, entry: PreExisting, unit: StoredUnit, **_: object) -> str:
    """The change that fixes the pre-existing failure `entry`, written if there is none."""
    failure = Flake(
        test=entry.test,
        unit=entry.unit,
        command=entry.command,
        output=entry.line,
        at=entry.at,
        failing=True,
    )
    return str(
        wait_on_regression(
            inst,
            failure,
            unit,
            kind=FixKind.PRE_EXISTING,
            runtime=None,
            base_output=entry.base_output,
            wait=False,
            say=lambda message: None,
        )
    )


class DefaultAgent:
    """The agent a test gets when it injects none: it writes a complete, valid change into the
    change directory it was given, whatever the test, and answers that it is done."""

    def __init__(self) -> None:
        self.runtime = StandInRuntime(act=self.act)

    def act(self, request: AgentRequest) -> None:
        assert request.planning_change_dir is not None
        # The test the agent is asked about is the one its prompt tells it to name.
        asked = re.search(r"exactly `Failing test: ([^`]+)`", request.prompt)
        write_change(
            request.planning_change_dir,
            test=asked[1] if asked else TEST,
            kind=asked_kind(request),
        )


def install(monkeypatch: pytest.MonkeyPatch) -> DefaultAgent:
    """Put a `DefaultAgent` behind the agent step's runtime lookup and the OpenSpec stand-in
    behind its check of its change, over the changes the planning repo it is asked about holds."""
    agent = DefaultAgent()
    # Only the agent step's own lookup: runtime selection is tested as it is.
    monkeypatch.setattr(regression_agent, "runtimes", SimpleNamespace(active=lambda: agent.runtime))
    real = regression_agent.validation_report

    # Only the agent step's own check of its change: every other caller of OpenSpec is
    # tested as it is.
    def report(planning: Path, change: str, *, run_openspec: openspec.Run | None = None, **rest):
        if run_openspec is None:
            folders = [found for found in planning.glob("*/changes") if found.is_dir()]
            run_openspec = validating(folders[0] if folders else planning / "changes")
        return real(planning, change, run_openspec=run_openspec, **rest)

    monkeypatch.setattr(regression_agent, "validation_report", report)
    return agent
