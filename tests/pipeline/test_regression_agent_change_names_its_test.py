"""The change the agent writes names its test in the title of group 1 (spec: regression-agent), so
the reproduction check of a fix unit can read the test with `flakes.fix_change_test`. A group 1 that
does not title the test id is rewritten once and then held. The agent is a stand-in that writes a
canned change; no model runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import fix_change_test, next_fix_name
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

TITLE_RULE = "Make `<test>` deterministic"
TITLED = f"Make `{TEST}` deterministic"

TEST_CODE = {"tasks": group_tasks(FIX_THE_TEST), "proposal": proposal_for_test_code()}
UNREPRODUCIBLE = {
    "tasks": group_tasks("Test: with a fake clock, the label follows the config.", FIX_THE_SOURCE),
    "proposal": PROPOSAL,
}
RACE_TASK = {
    "tasks": group_tasks("Test: reproduce the race.", FIX_THE_TEST),
    "proposal": proposal_for_test_code(),
}

# A group 1 whose title does not name the test id: no test at all, or a test that is not the one.
UNTITLED = {
    "no-test": {
        **TEST_CODE,
        "tasks": TEST_CODE["tasks"].replace(TITLED, "Make the label test deterministic"),
    },
    "another-test": {
        **TEST_CODE,
        "tasks": TEST_CODE["tasks"].replace(
            TITLED, "Make `tests/test_other.py::test_x` deterministic"
        ),
    },
    "no-backticks": {
        **TEST_CODE,
        "tasks": TEST_CODE["tasks"].replace(TITLED, f"Make {TEST} deterministic"),
    },
}


def test_the_prompt_states_the_title_rule(installation: Installation, tmp_path: Path) -> None:
    agent = Attempts(installation, next_fix_name(installation, TEST), TEST_CODE)

    run(installation, tmp_path, agent.runtime)

    assert TITLE_RULE in agent.runtime.requests[0].prompt


def test_a_change_titling_its_test_gives_a_test_a_reproduction_check_can_read(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, TEST_CODE)

    outcome = run(installation, tmp_path, agent.runtime)

    tasks = (installation.changes_dir / name / "tasks.md").read_text()
    assert outcome == FixOutcome(change=name)
    assert f"] [unit-test] [contract] {TITLED}" in tasks
    assert fix_change_test(installation, name) == TEST
    assert TITLE_RULE in agent.runtime.requests[0].prompt


def test_a_cause_in_test_code_has_no_task_to_reproduce_the_race(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, RACE_TASK, TEST_CODE)

    outcome = run(installation, tmp_path, agent.runtime)

    tasks = (installation.changes_dir / name / "tasks.md").read_text()
    assert outcome == FixOutcome(change=name)
    assert "reproduce the race" not in tasks
    assert TITLE_RULE in agent.runtime.requests[0].prompt


def test_a_change_for_a_test_that_cannot_be_reproduced_still_names_its_test(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, UNREPRODUCIBLE)

    outcome = run(installation, tmp_path, agent.runtime)

    assert outcome == FixOutcome(change=name)
    assert fix_change_test(installation, name) == TEST
    assert TITLE_RULE in agent.runtime.requests[0].prompt


@pytest.mark.parametrize("step", UNTITLED.values(), ids=UNTITLED.keys())
def test_a_group_1_that_names_no_test_id_is_rewritten_once(
    installation: Installation, tmp_path: Path, step: dict[str, str]
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, step, TEST_CODE)

    outcome = run(installation, tmp_path, agent.runtime)

    assert outcome == FixOutcome(change=name)
    assert len(agent.runtime.requests) == 2
    assert TITLE_RULE in refusal_of(agent.runtime.requests[1])


def test_a_group_1_that_still_names_no_test_id_is_held_for_a_person(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, UNTITLED["no-test"])

    outcome = run(installation, tmp_path, agent.runtime)

    assert len(agent.runtime.requests) == 2
    assert outcome.change == name
    assert outcome.held
    assert TITLE_RULE in outcome.reason
