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
    FIX_THE_TEST,
    PROPOSAL,
    TEST,
    Attempts,
    group_tasks,
    proposal_for_test_code,
    refusal_of,
    run,
)

# The module `widget` and its test file in a python-shaped checkout and a node-shaped one, and the
# task that adds a second test file for it.
PLACEMENTS = {
    "python": (
        ("src/widget.py", "tests/test_widget.py"),
        "Add the counted-call case to a new `tests/test_widget_label.py`, beside the others.",
        "tests/test_widget_label.py",
    ),
    "node": (
        ("web/src/widget.ts", "web/src/widget.test.ts"),
        "Add the counted-call case to a new `web/src/widget.label.test.ts`.",
        "web/src/widget.label.test.ts",
    ),
}
NEW_MODULE = (
    "Add `src/gadget.py` with the label cache, and its cases in a new `tests/test_gadget.py`."
)
# A new logic file whose name extends the name of a module that has a test file.
NEW_MODULE_OF_THE_SAME_SUBJECT = (
    "Add `src/widget_cache.py` and its cases in a new `tests/test_widget_cache.py`."
)
NEW_NODE_MODULE_OF_THE_SAME_SUBJECT = (
    "Add `web/src/widget.label.ts` and its cases in a new `web/src/widget.label.test.ts`."
)

WITHOUT_STANDARD = PROPOSAL.replace(
    "- Judgement: the implementation is wrong.", "- Judgement: the test is wrong."
)


def cited(standard: str) -> dict[str, str]:
    """The change of a cause in test code that cites `standard`."""
    return {"tasks": group_tasks(FIX_THE_TEST), "proposal": proposal_for_test_code(standard)}


def with_checkout(tmp_path: Path, *paths: str) -> None:
    """The base checkout holds `paths` (the python-shaped module and its test by default)."""
    for path in paths or PLACEMENTS["python"][0]:
        (tmp_path / "base-checkout" / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "base-checkout" / path).write_text("")


@pytest.mark.parametrize("standard", ["T5", "T6", "T8a", "T12a", "T17", "T21"])
def test_a_proposal_citing_a_standard_of_the_catalogue_is_accepted(
    installation: Installation, tmp_path: Path, standard: str
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, cited(standard))

    outcome = run(installation, tmp_path, agent.runtime)

    assert outcome == FixOutcome(change=name)
    assert len(agent.runtime.requests) == 1
    assert "Standard: T" in agent.runtime.requests[0].prompt


@pytest.mark.parametrize(
    "defect",
    [
        {"proposal": WITHOUT_STANDARD},
        cited("T99"),
        cited("T8b"),
        cited("T5z"),
        cited("the wall-clock one"),
    ],
    ids=[
        "no-line",
        "not-in-the-catalogue",
        "unlisted-letter",
        "letter-on-a-standard",
        "not-a-number",
    ],
)
def test_a_test_code_proposal_without_a_standard_is_rewritten_once(
    installation: Installation, tmp_path: Path, defect: dict[str, str]
) -> None:
    name = next_fix_name(installation, TEST)
    broken = {"tasks": group_tasks(FIX_THE_TEST), **defect}
    agent = Attempts(installation, name, broken, cited("T5"))

    outcome = run(installation, tmp_path, agent.runtime)

    assert outcome == FixOutcome(change=name)
    assert len(agent.runtime.requests) == 2
    assert "Standard: T" in refusal_of(agent.runtime.requests[1])


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
    agent = Attempts(installation, next_fix_name(installation, TEST), cited("T5"))

    run(installation, tmp_path, agent.runtime)

    prompt = agent.runtime.requests[0].prompt
    assert "T2" in prompt
    assert "existing test file" in prompt
    assert "new logic file" in prompt


@pytest.mark.parametrize(("files", "task", "new_file"), PLACEMENTS.values(), ids=PLACEMENTS.keys())
def test_a_task_that_adds_a_test_file_for_a_module_that_has_one_is_rewritten_once(
    installation: Installation,
    tmp_path: Path,
    files: tuple[str, ...],
    task: str,
    new_file: str,
) -> None:
    with_checkout(tmp_path, *files)
    name = next_fix_name(installation, TEST)
    misplaced = {**cited("T5"), "tasks": group_tasks(task)}
    agent = Attempts(installation, name, misplaced, cited("T5"))

    outcome = run(installation, tmp_path, agent.runtime)

    assert outcome == FixOutcome(change=name)
    assert len(agent.runtime.requests) == 2
    assert new_file in refusal_of(agent.runtime.requests[1])


@pytest.mark.parametrize(("files", "task", "new_file"), PLACEMENTS.values(), ids=PLACEMENTS.keys())
def test_a_task_that_still_adds_a_test_file_for_a_module_that_has_one_is_held(
    installation: Installation,
    tmp_path: Path,
    files: tuple[str, ...],
    task: str,
    new_file: str,
) -> None:
    with_checkout(tmp_path, *files)
    name = next_fix_name(installation, TEST)
    misplaced = {**cited("T5"), "tasks": group_tasks(task)}
    agent = Attempts(installation, name, misplaced)

    outcome = run(installation, tmp_path, agent.runtime)

    assert len(agent.runtime.requests) == 2
    assert outcome.held
    assert new_file in outcome.reason


@pytest.mark.parametrize(
    ("task", "files"),
    [
        (NEW_MODULE, PLACEMENTS["python"][0]),
        (NEW_MODULE_OF_THE_SAME_SUBJECT, PLACEMENTS["python"][0]),
        (NEW_NODE_MODULE_OF_THE_SAME_SUBJECT, PLACEMENTS["node"][0]),
    ],
    ids=["unrelated-name", "name-extends-a-module", "node-name-extends-a-module"],
)
def test_a_new_test_file_for_a_new_logic_file_is_accepted(
    installation: Installation, tmp_path: Path, task: str, files: tuple[str, ...]
) -> None:
    with_checkout(tmp_path, *files)
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, {"tasks": group_tasks(task), "proposal": PROPOSAL})

    outcome = run(installation, tmp_path, agent.runtime)

    assert outcome == FixOutcome(change=name)
    assert len(agent.runtime.requests) == 1
    assert "new logic file" in agent.runtime.requests[0].prompt
