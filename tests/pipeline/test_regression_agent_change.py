"""The change the regression agent writes (spec: regression-agent).

The agent is a stand-in runtime whose action writes files into the change directory, as the real
one does; the planning repo and the code repo are folders under the test's temporary path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.config import models
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import Flake, flake_record, next_fix_name
from agent_build_kit.pipeline.regression_agent import FixKind, FixOutcome, write_fix_change
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

## What Changes

- Read the label when it is rendered.

## Impact

- app: the widget.
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


def writes(
    inst: Installation, name: str, *, flag: str = " [contract]", priority: str = "Priority: 1\n\n"
) -> None:
    """The files of a complete change named `name`."""
    root = inst.changes_dir / name
    (root / "specs" / "label").mkdir(parents=True, exist_ok=True)
    (root / "proposal.md").write_text(PROPOSAL.format(test=TEST, base=BASE))
    (root / "design.md").write_text("## Context\n\nThe label is read too early.\n")
    (root / "tasks.md").write_text(TASKS.format(flag=flag, priority=priority))
    (root / "specs" / "label" / "spec.md").write_text(SPEC)


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
    return write_fix_change(
        inst,
        failure(),
        stored_unit("feature/1", change="feature", groups=(1,)),
        kind=kind,
        base=BASE,
        base_output="" if kind is FixKind.FLAKY else BASE_OUTPUT,
        runtime=runtime,
        cwd=tmp_path / "base-checkout",
    )


def test_the_change_it_wrote_is_the_outcome_and_the_agent_is_told_what_to_find(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, {})

    outcome = run(installation, tmp_path, agent.runtime)

    assert outcome == FixOutcome(change=name)
    prompt = agent.runtime.request.prompt
    assert name in prompt
    assert TEST in prompt
    assert BASE in prompt
    assert failure().output in prompt


@pytest.mark.parametrize("kind", list(FixKind))
def test_the_evidence_of_each_kind_reaches_the_agent(
    installation: Installation, tmp_path: Path, kind: FixKind
) -> None:
    flake_record(installation).append(failure(unit="earlier/9", change="fix-test-earlier"))
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, {})

    run(installation, tmp_path, agent.runtime, kind=kind)

    prompt = agent.runtime.request.prompt
    assert EVIDENCE in prompt
    assert kind.value in prompt
    assert "earlier/9" in prompt
    assert (BASE_OUTPUT in prompt) is (kind is not FixKind.FLAKY)


def test_the_agent_runs_as_the_regression_role_and_writes_only_its_change_directory(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, {})

    run(installation, tmp_path, agent.runtime)

    request = agent.runtime.request
    assert request.role == "regression"
    assert request.model == models().regression
    assert request.cwd == tmp_path / "base-checkout"
    assert request.policy is not None and request.policy.sandbox is not None
    assert request.policy.sandbox.write == (installation.changes_dir / name,)


@pytest.mark.parametrize(
    "defect",
    [{"flag": ""}, {"priority": ""}, {"flag": " [contract"}],
    ids=["no-contract", "no-priority", "broken-tag"],
)
def test_a_change_that_fails_the_check_is_rewritten_once(
    installation: Installation, tmp_path: Path, defect: dict[str, str]
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, defect, {})

    outcome = run(installation, tmp_path, agent.runtime)

    assert outcome == FixOutcome(change=name)
    assert len(agent.runtime.requests) == 2


@pytest.mark.parametrize(
    "defect", [{"flag": ""}, {"priority": ""}], ids=["no-contract", "no-priority"]
)
def test_a_change_that_still_fails_the_check_is_held_for_a_person(
    installation: Installation, tmp_path: Path, defect: dict[str, str]
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, defect)

    outcome = run(installation, tmp_path, agent.runtime)

    assert len(agent.runtime.requests) == 2
    assert outcome.change == name
    assert outcome.held
    assert outcome.reason


def test_a_change_the_agent_could_not_decide_is_held_without_a_second_run(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, {})
    agent.runtime.answer = f"I looked at the history and cannot tell.\n{UNDECIDED}\n"

    outcome = run(installation, tmp_path, agent.runtime)

    assert len(agent.runtime.requests) == 1
    assert outcome.change == name
    assert outcome.held
    assert outcome.reason
