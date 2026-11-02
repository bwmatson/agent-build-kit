"""The regression agent's stand-in and the change it writes, shared by the tests of the agent and
of its change check (spec: regression-agent, regression-same-exposure).

The agent is a stand-in runtime whose action writes files into the change directory, as the real
one does.
"""

from __future__ import annotations

import json
import re
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
- Kind: {kind}

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

## 1. [app] [unit-test]{flag} Make `{test}` deterministic

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


# The proposal of a cause in test code: the test is wrong, and the standard it breaks is named.
TEST_CODE_PROPOSAL = PROPOSAL.replace(
    "- Judgement: the implementation is wrong.\n",
    "- Judgement: the test is wrong.\n- Standard: {standard}\n",
)

# The tasks.md of one `[contract]` group with a priority; `{tasks}` is its task lines.
GROUP = """\
# Tasks

Acceptance: none — nothing a consumer sees changes.

## 1. [app] [unit-test] [contract] Make `{test}` deterministic

Priority: 1

Done when the test passes.
{header}
{tasks}"""

# The task of a cause in test code, and the one of a cause in a source file.
FIX_THE_TEST = "Replace the wall-clock assertion in `tests/test_widget.py` with a counted call."
FIX_THE_SOURCE = "Read the label when it is rendered in `src/widget.py`."


def group_tasks(*tasks: str, header: str = "") -> str:
    """The tasks.md of one `[contract]` group whose task lines are `tasks`, numbered from 1.1,
    with `header` (a line such as `Tests: required — ...`) under its `Done when` sentence."""
    lines = "".join(f"- [ ] 1.{n} {text}\n" for n, text in enumerate(tasks, 1))
    return GROUP.format(test=TEST, tasks=lines, header=header)


def refusal_of(request: AgentRequest) -> str:
    """What the rewrite prompt of `request` adds to the first one: the reasons the change was
    refused."""
    return request.prompt.split("The change you wrote was refused", 1)[1]


def proposal_for_test_code(standard: str = "T5") -> str:
    """The proposal of a cause in test code that cites `standard`; `write_change` fills the rest."""
    return TEST_CODE_PROPOSAL.replace("{standard}", standard)


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
    kind: str = "regression",
) -> None:
    """The files of a complete change for `test` of `kind` in `root`; `tasks` replaces the whole
    tasks.md, `exposure` is the proposal's `Same exposure` section, left out when empty, and
    `proposal` replaces the whole proposal."""
    (root / "specs" / "label").mkdir(parents=True, exist_ok=True)
    (root / "proposal.md").write_text(
        proposal.format(test=test, base=BASE, exposure=exposure, kind=kind)
    )
    (root / "design.md").write_text("## Context\n\nThe label is read too early.\n")
    (root / "tasks.md").write_text(tasks or TASKS.format(flag=flag, priority=priority, test=test))
    (root / "specs" / "label" / "spec.md").write_text(spec)


def asked_kind(request: AgentRequest) -> str:
    """The kind of failure the prompt tells the agent to name on its `Kind:` line."""
    asked = re.search(r"exactly `Kind: ([^`]+)`", request.prompt)
    return asked[1] if asked else "regression"


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
        writes(self.inst, self.name, **{"kind": asked_kind(request), **step})


def run(
    inst: Installation,
    tmp_path: Path,
    runtime: StandInRuntime,
    *,
    kind: FixKind = FixKind.REGRESSION,
    failed: Flake | None = None,
) -> FixOutcome:
    return run_regression_agent(
        inst,
        failed or failure(),
        stored_unit("feature/1", change="feature", groups=(1,)),
        kind=kind,
        base=BASE,
        base_output="" if kind is FixKind.FLAKY else BASE_OUTPUT,
        runtime=runtime,
        cwd=tmp_path / "base-checkout",
        run_openspec=openspec_checking(inst),
    )
