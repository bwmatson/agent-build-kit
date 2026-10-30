"""The regression agent's stand-ins: a runtime that writes a change into the change directory as the
real agent does, the files of a complete change, and a stand-in for `openspec validate` (the real
CLI needs node).

`DefaultAgent` is what every test gets when it injects no runtime: the pipeline's handlers then
run the real agent step against it, and `install` puts it behind `runtimes.active()`.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_build_kit import openspec
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import regression_agent
from agent_build_kit.pipeline.flakes import Flake
from agent_build_kit.pipeline.regression_agent import FixKind, wait_on_regression
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.untouched_failures import PreExisting
from agent_build_kit.runtimes import AgentRequest, AgentRuntime
from tests.runtimes.stand_in import StandInRuntime

TEST = "tests/test_widget.py::test_renders_the_label"
BASE = "3f9c2a1d0b7e4c5a8d6e1f203a4b5c6d7e8f9a0b"
BASE_OUTPUT = "FAILED tests/test_widget.py::test_renders_the_label - base run says assert 1 == 2\n"
EVIDENCE = "load before: 14.2; rerun 1 passed; rerun 2 passed; tree unchanged"
UNDECIDED = "JUDGEMENT: undecided"

PROPOSAL = """\
## Why

`{test}` fails because the label is built before the config is read.

- Cause: the label is read at import time.
- Since: commit 3f9c2a1d, 2026-02-11.
- Base: {base}
- Judgement: the implementation is wrong.

## What Changes

- Read the label when it is rendered.

## Impact

- app: the widget.

## Same exposure

Same exposure: none, the cause is specific to this test
"""

TASKS = """\
# Tasks

Acceptance: none — nothing a consumer sees changes.

## 1. [app] [unit-test]{flag} Read the label when it is rendered

{priority}Done when the test passes.

- [ ] 1.1 Test: the label follows the config.
- [ ] 1.2 Read the label at render time.
"""

SPEC = """\
## ADDED Requirements

### Requirement: The label follows the config

The label SHALL be read when it is rendered.

#### Scenario: Config changes

- **WHEN** the config changes
- **THEN** the next render shows it
"""


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


def openspec_checking(inst: Installation):
    return validating(inst.changes_dir)


def write_change(
    root: Path,
    *,
    flag: str = " [contract]",
    priority: str = "Priority: 1\n\n",
    spec: str = SPEC,
    tasks: str = "",
    proposal: str = PROPOSAL,
) -> None:
    """The files of a complete change in `root`; `tasks` replaces the whole tasks.md."""
    (root / "specs" / "label").mkdir(parents=True, exist_ok=True)
    (root / "proposal.md").write_text(proposal.format(test=TEST, base=BASE))
    (root / "design.md").write_text("## Context\n\nThe label is read too early.\n")
    (root / "tasks.md").write_text(tasks or TASKS.format(flag=flag, priority=priority))
    (root / "specs" / "label" / "spec.md").write_text(spec)


def writes(inst: Installation, name: str, **parts: str) -> None:
    """The files of a complete change named `name` in the planning repo."""
    write_change(inst.changes_dir / name, **parts)


def waited_on(
    inst: Installation,
    failure: Flake,
    unit: StoredUnit,
    *,
    kind: FixKind = FixKind.FLAKY,
    wait: bool = True,
    runtime: AgentRuntime | None = None,
) -> str | None:
    """`wait_on_regression` as the handlers call it, with the default stand-in agent behind it
    unless `runtime` is given."""
    return wait_on_regression(
        inst, failure, unit, kind=kind, runtime=runtime, wait=wait, say=lambda message: None
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


class Attempts:
    """A stand-in agent that writes the change its run's step describes, in order; the last step
    is used again for any run after it."""

    def __init__(self, inst: Installation, name: str, *steps: dict[str, str]) -> None:
        self.inst = inst
        self.name = name
        self.steps = steps
        self.runtime = StandInRuntime(act=self.act)

    def act(self, request: AgentRequest) -> None:
        step = self.steps[min(len(self.runtime.requests) - 1, len(self.steps) - 1)]
        writes(self.inst, self.name, **step)


class DefaultAgent:
    """The agent a test gets when it injects none: it writes a complete, valid change into the
    change directory it was given, whatever the test, and answers that it is done."""

    def __init__(self) -> None:
        self.runtime = StandInRuntime(act=self.act)

    def act(self, request: AgentRequest) -> None:
        assert request.planning_change_dir is not None
        write_change(request.planning_change_dir)


def install(monkeypatch: pytest.MonkeyPatch) -> DefaultAgent:
    """Put a `DefaultAgent` behind `runtimes.active()` and the OpenSpec stand-in behind a
    validation that injects no runner, over the changes the planning repo it is asked about
    holds."""
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
