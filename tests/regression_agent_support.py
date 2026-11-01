"""The regression agent's stand-in and the change it writes, shared by the tests of the agent and
of its change check (spec: regression-agent, regression-same-exposure).

The agent is a stand-in runtime whose action writes files into the change directory, as the real
one does.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import Flake
from agent_build_kit.pipeline.regression_agent import FixKind, FixOutcome, run_regression_agent
from agent_build_kit.runtimes import AgentRequest
from tests.factories import stored_unit
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
- Failing test: {test}

## What Changes

- Read the label when it is rendered.

## Impact

- app: the widget.
{exposure}"""

# The `Same exposure` section of a cause that is not a pattern.
NO_EXPOSURE = """
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


def failure(**overrides) -> Flake:
    fields: dict[str, Any] = {
        "test": TEST,
        "unit": "feature/1",
        "command": "uv run pytest -n auto -q",
        "output": "FAILED tests/test_widget.py::test_renders_the_label - assert 'a' == 'b'\n",
        "at": datetime(2026, 3, 1, 9, 30, tzinfo=UTC),
        "evidence": EVIDENCE,
    }
    return Flake(**{**fields, **overrides})


def openspec_checking(inst: Installation):
    """A stand-in for `openspec validate` that refuses a change whose delta spec holds a
    requirement with no scenario, as the real one does (the real CLI needs node)."""

    def validate(argv, *, cwd, **kwargs) -> subprocess.CompletedProcess:
        items = []
        for change in sorted(p for p in inst.changes_dir.iterdir() if p.is_dir()):
            specs = [spec.read_text() for spec in change.glob("specs/*/spec.md")]
            valid = all("#### Scenario:" in text for text in specs)
            issues = [] if valid else [{"message": "a requirement has no scenario"}]
            items.append({"id": change.name, "valid": valid, "issues": issues})
        return subprocess.CompletedProcess(argv, 0, json.dumps({"items": items}), "")

    return validate


def write_change(
    root: Path,
    *,
    flag: str = " [contract]",
    priority: str = "Priority: 1\n\n",
    spec: str = SPEC,
    tasks: str = "",
    exposure: str = NO_EXPOSURE,
    proposal: str = PROPOSAL,
    test: str = TEST,
) -> None:
    """The files of a complete change for `test` in `root`; `tasks` replaces the whole tasks.md,
    `exposure` is the proposal's `Same exposure` section, left out when empty, and `proposal`
    replaces the whole proposal."""
    (root / "specs" / "label").mkdir(parents=True, exist_ok=True)
    (root / "proposal.md").write_text(proposal.format(test=test, base=BASE, exposure=exposure))
    (root / "design.md").write_text("## Context\n\nThe label is read too early.\n")
    (root / "tasks.md").write_text(tasks or TASKS.format(flag=flag, priority=priority))
    (root / "specs" / "label" / "spec.md").write_text(spec)


def writes(inst: Installation, name: str, **parts: str) -> None:
    """The files of a complete change named `name` in the planning repo."""
    write_change(inst.changes_dir / name, **parts)


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


def run(
    inst: Installation,
    tmp_path: Path,
    runtime: StandInRuntime,
    *,
    kind: FixKind = FixKind.REGRESSION,
) -> FixOutcome:
    return run_regression_agent(
        inst,
        failure(),
        stored_unit("feature/1", change="feature", groups=(1,)),
        kind=kind,
        base=BASE,
        base_output="" if kind is FixKind.FLAKY else BASE_OUTPUT,
        runtime=runtime,
        cwd=tmp_path / "base-checkout",
        run_openspec=openspec_checking(inst),
    )
