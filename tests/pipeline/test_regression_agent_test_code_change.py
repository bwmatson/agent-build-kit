"""A fix for test code carries no test of its own (spec: regression-agent): when the cause the
agent names is in test code, the change's groups name only test files and hold no `Test:` task,
so `abk tags` shows them as `tests_only`; a cause in a source file keeps a `Test:` task before the
fix. The agent is a stand-in that writes a canned change; no model runs.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import next_fix_name
from agent_build_kit.pipeline.regression_agent import FixOutcome
from tests.regression_agent_support import (
    FIX_THE_SOURCE,
    FIX_THE_TEST,
    PROPOSAL,
    TEST,
    Attempts,
    group_tasks,
    proposal_for_test_code,
    refusal_of,
    run,
)

ASK_FOR_A_REPRODUCTION = (
    "Test: add a case to `tests/test_widget.py` that reproduces the race before the fix."
)
TEST_BEFORE_THE_FIX = (
    "Test: with a fake clock in `tests/test_widget.py`, the label follows the config."
)

TEST_CODE = {"tasks": group_tasks(FIX_THE_TEST), "proposal": proposal_for_test_code()}
ASKING = {**TEST_CODE, "tasks": group_tasks(ASK_FOR_A_REPRODUCTION, FIX_THE_TEST)}
SOURCE_CODE = {"tasks": group_tasks(TEST_BEFORE_THE_FIX, FIX_THE_SOURCE), "proposal": PROPOSAL}

# A source fix with a `[unit-test]` group holding the `Test:` task, and an `[e2e-test]` group
# whose task is worded `Test:` too, as the authoring skill words an e2e task.
WITH_AN_E2E_GROUP = {
    "tasks": group_tasks(TEST_BEFORE_THE_FIX, FIX_THE_SOURCE)
    + "\n## 2. [app] [e2e-test] The widget shows the label end to end\n\n"
    "Needs: group 1\n\nDone when the entry point shows the label.\n\n"
    "- [ ] 2.1 Test: run the entry point and see the label.\n",
    "proposal": PROPOSAL,
}

# A change that judges the test wrong but whose group does not read as `tests_only`: the tasks
# name no path, or the group says tests are required.
PATH_FREE = group_tasks("Test: reproduce the race.", "Make the wait bounded.")
TESTS_REQUIRED = group_tasks(FIX_THE_TEST, header="Tests: required — a reason\n")
NOT_TESTS_ONLY = {
    "path-free": {**TEST_CODE, "tasks": PATH_FREE},
    "tests-required": {**TEST_CODE, "tasks": TESTS_REQUIRED},
}


def tags_of(inst: Installation, name: str, capsys: pytest.CaptureFixture) -> str:
    """The first group line `abk tags` prints for the change `name`."""
    cli.cmd_tags(argparse.Namespace(all=False, change=name), inst)
    out = capsys.readouterr().out.splitlines()
    return next(line for line in out if line.strip().startswith("1."))


def test_a_cause_in_test_code_gives_groups_with_no_test_task(
    installation: Installation, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, TEST_CODE)

    outcome = run(installation, tmp_path, agent.runtime)

    assert outcome == FixOutcome(change=name)
    assert len(agent.runtime.requests) == 1
    assert "tests_only" in tags_of(installation, name, capsys)
    # The prompt tells the agent that a test-code cause is a `tests_only` change.
    assert "tests_only" in agent.runtime.requests[0].prompt


def test_a_cause_in_a_source_file_keeps_the_test_task_before_the_fix(
    installation: Installation, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, SOURCE_CODE)

    outcome = run(installation, tmp_path, agent.runtime)

    assert outcome == FixOutcome(change=name)
    assert len(agent.runtime.requests) == 1
    assert "tests_only" not in tags_of(installation, name, capsys)
    assert "`Test:` task" in agent.runtime.requests[0].prompt


def test_an_e2e_group_may_hold_a_test_task_beside_a_source_fix(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, WITH_AN_E2E_GROUP)

    outcome = run(installation, tmp_path, agent.runtime)

    assert outcome == FixOutcome(change=name)
    assert len(agent.runtime.requests) == 1


def test_a_test_only_fix_that_asks_for_a_reproduction_test_is_rewritten_once(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, ASKING, TEST_CODE)

    outcome = run(installation, tmp_path, agent.runtime)

    assert outcome == FixOutcome(change=name)
    assert len(agent.runtime.requests) == 2
    assert "no `Test:` task" in refusal_of(agent.runtime.requests[1])


def test_a_test_only_fix_that_still_asks_for_a_reproduction_test_is_held(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, ASKING)

    outcome = run(installation, tmp_path, agent.runtime)

    assert len(agent.runtime.requests) == 2
    assert outcome.change == name
    assert outcome.held
    assert "Test:" in outcome.reason


@pytest.mark.parametrize("defect", NOT_TESTS_ONLY.values(), ids=NOT_TESTS_ONLY.keys())
def test_a_test_wrong_judgement_with_a_group_that_is_not_tests_only_is_rewritten_once(
    installation: Installation, tmp_path: Path, defect: dict[str, str]
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, defect, TEST_CODE)

    outcome = run(installation, tmp_path, agent.runtime)

    assert outcome == FixOutcome(change=name)
    assert len(agent.runtime.requests) == 2
    assert "not `tests_only`" in refusal_of(agent.runtime.requests[1])


@pytest.mark.parametrize("defect", NOT_TESTS_ONLY.values(), ids=NOT_TESTS_ONLY.keys())
def test_a_test_wrong_judgement_with_a_group_that_stays_not_tests_only_is_held(
    installation: Installation, tmp_path: Path, defect: dict[str, str]
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, defect)

    outcome = run(installation, tmp_path, agent.runtime)

    assert len(agent.runtime.requests) == 2
    assert outcome.held
    assert "not `tests_only`" in outcome.reason
