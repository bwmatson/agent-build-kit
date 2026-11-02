"""The change for a cause in test code cites the standard it breaks and places its tests by the
placement rule (spec: regression-agent): a `Standard: T<n>` line naming a standard of the test
catalogue, and a new case in the existing test file of the module it exercises, a new test file
only for a new logic file. The agent is a stand-in that writes a canned change; no model runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import next_fix_name
from agent_build_kit.pipeline.regression_agent import FixOutcome
from tests.regression_agent_support import (
    PROPOSAL,
    TEST,
    Attempts,
    group_tasks,
    proposal_for_test_code,
    run,
)

FIX_THE_TEST = "Replace the wall-clock assertion in `tests/test_widget.py` with a counted call."
NEW_FILE_FOR_AN_OLD_MODULE = (
    "Add the counted-call case to a new `tests/test_widget_label.py`, beside the others."
)
NEW_MODULE = (
    "Add `src/gadget.py` with the label cache, and its cases in a new `tests/test_gadget.py`."
)

WITHOUT_STANDARD = PROPOSAL.replace(
    "- Judgement: the implementation is wrong.", "- Judgement: the test is wrong."
)


def test_code(standard: str) -> dict[str, str]:
    return {"tasks": group_tasks(FIX_THE_TEST), "proposal": proposal_for_test_code(standard)}


def with_checkout(tmp_path: Path) -> None:
    """The base checkout holds `src/widget.py` and the test file that exercises it."""
    for path in ("src/widget.py", "tests/test_widget.py"):
        (tmp_path / "base-checkout" / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "base-checkout" / path).write_text("")


@pytest.mark.parametrize("standard", ["T5", "T6", "T8a", "T17", "T21"])
def test_a_proposal_citing_a_standard_of_the_catalogue_is_accepted(
    installation: Installation, tmp_path: Path, standard: str
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, test_code(standard))

    outcome = run(installation, tmp_path, agent.runtime)

    assert outcome == FixOutcome(change=name)
    assert len(agent.runtime.requests) == 1
    assert "Standard: T" in agent.runtime.requests[0].prompt


@pytest.mark.parametrize(
    "defect",
    [
        {"proposal": WITHOUT_STANDARD},
        test_code("T99"),
        test_code("the wall-clock one"),
    ],
    ids=["no-line", "not-in-the-catalogue", "not-a-number"],
)
def test_a_test_code_proposal_without_a_standard_is_rewritten_once(
    installation: Installation, tmp_path: Path, defect: dict[str, str]
) -> None:
    name = next_fix_name(installation, TEST)
    broken = {"tasks": group_tasks(FIX_THE_TEST), **defect}
    agent = Attempts(installation, name, broken, test_code("T5"))

    outcome = run(installation, tmp_path, agent.runtime)

    assert outcome == FixOutcome(change=name)
    assert len(agent.runtime.requests) == 2
    assert "Standard: T" in agent.runtime.requests[1].prompt


def test_a_proposal_still_without_a_standard_is_held_for_a_person(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(
        installation, name, {"tasks": group_tasks(FIX_THE_TEST), "proposal": WITHOUT_STANDARD}
    )

    outcome = run(installation, tmp_path, agent.runtime)

    assert len(agent.runtime.requests) == 2
    assert outcome.held
    assert "Standard" in outcome.reason


def test_the_prompt_states_the_placement_rule(installation: Installation, tmp_path: Path) -> None:
    agent = Attempts(installation, next_fix_name(installation, TEST), test_code("T5"))

    run(installation, tmp_path, agent.runtime)

    prompt = agent.runtime.requests[0].prompt
    assert "T2" in prompt
    assert "existing test file" in prompt
    assert "new logic file" in prompt


def test_a_task_that_adds_a_test_file_for_a_module_that_has_one_is_rewritten_once(
    installation: Installation, tmp_path: Path
) -> None:
    with_checkout(tmp_path)
    name = next_fix_name(installation, TEST)
    misplaced = {**test_code("T5"), "tasks": group_tasks(NEW_FILE_FOR_AN_OLD_MODULE)}
    agent = Attempts(installation, name, misplaced, test_code("T5"))

    outcome = run(installation, tmp_path, agent.runtime)

    assert outcome == FixOutcome(change=name)
    assert len(agent.runtime.requests) == 2
    assert "tests/test_widget_label.py" in agent.runtime.requests[1].prompt


def test_a_task_that_still_adds_a_test_file_for_a_module_that_has_one_is_held(
    installation: Installation, tmp_path: Path
) -> None:
    with_checkout(tmp_path)
    name = next_fix_name(installation, TEST)
    misplaced = {**test_code("T5"), "tasks": group_tasks(NEW_FILE_FOR_AN_OLD_MODULE)}
    agent = Attempts(installation, name, misplaced)

    outcome = run(installation, tmp_path, agent.runtime)

    assert len(agent.runtime.requests) == 2
    assert outcome.held
    assert "tests/test_widget_label.py" in outcome.reason


def test_a_new_test_file_for_a_new_logic_file_is_accepted(
    installation: Installation, tmp_path: Path
) -> None:
    with_checkout(tmp_path)
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, {"tasks": group_tasks(NEW_MODULE), "proposal": PROPOSAL})

    outcome = run(installation, tmp_path, agent.runtime)

    assert outcome == FixOutcome(change=name)
    assert len(agent.runtime.requests) == 1
    assert "new logic file" in agent.runtime.requests[0].prompt
