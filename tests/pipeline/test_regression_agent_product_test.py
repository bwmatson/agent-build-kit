"""The `Test:` task of a fix for a cause in a source file recreates the defect deterministically
(spec: regression-agent): a fake clock, an injected ordering or a stand-in dependency, named in the
task, and never only a rerun of the flaky test. The agent is a stand-in that writes a canned
change; no model runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import next_fix_name
from agent_build_kit.pipeline.regression_agent import FixOutcome
from tests.regression_agent_support import (
    FIX_THE_SOURCE,
    PROPOSAL,
    TEST,
    Attempts,
    group_tasks,
    refusal_of,
    run,
)


def source_fix(test_task: str) -> dict[str, str]:
    return {"tasks": group_tasks(test_task, FIX_THE_SOURCE), "proposal": PROPOSAL}


DETERMINISTIC = {
    "a-fake-clock": source_fix(
        "Test: in `tests/test_widget.py`, with a fake clock that is advanced past the config "
        "reload, the label follows the config."
    ),
    "an-injected-ordering": source_fix(
        "Test: in `tests/test_widget.py`, with the two loaders injected so the config loader "
        "returns before the render, the label follows the config."
    ),
    "a-stand-in-dependency": source_fix(
        "Test: in `tests/test_widget.py`, with a stand-in config store that answers late, "
        "the label follows the config."
    ),
    "on-a-continuation-line": source_fix(
        "Test: in `tests/test_widget.py`, the label follows the config\n"
        "  once a fake clock is advanced past the reload."
    ),
}

RERUNS = {
    "rerun": source_fix(f"Test: rerun `{TEST}` and see it fail before the fix and pass after."),
    "loop": source_fix(f"Test: run `{TEST}` in a loop of 50 until it fails."),
    "times": source_fix(f"Test: run `{TEST}` 50 times until it fails."),
    "on-a-continuation-line": source_fix(
        "Test: in `tests/test_widget.py`, the label follows the config;\n  rerun it until it fails."
    ),
}


def test_the_prompt_asks_for_a_deterministic_recreation(
    installation: Installation, tmp_path: Path
) -> None:
    agent = Attempts(installation, next_fix_name(installation, TEST), DETERMINISTIC["a-fake-clock"])

    run(installation, tmp_path, agent.runtime)

    prompt = agent.runtime.requests[0].prompt
    assert "deterministic" in prompt
    assert "fake clock" in prompt


@pytest.mark.parametrize("step", DETERMINISTIC.values(), ids=DETERMINISTIC.keys())
def test_a_test_task_that_recreates_the_defect_is_accepted(
    installation: Installation, tmp_path: Path, step: dict[str, str]
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, step)

    outcome = run(installation, tmp_path, agent.runtime)

    assert outcome == FixOutcome(change=name)
    assert len(agent.runtime.requests) == 1
    assert "deterministic" in agent.runtime.requests[0].prompt


@pytest.mark.parametrize("rerun", RERUNS.values(), ids=RERUNS.keys())
def test_a_task_that_only_reruns_the_original_test_is_rewritten_once(
    installation: Installation, tmp_path: Path, rerun: dict[str, str]
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, rerun, DETERMINISTIC["a-fake-clock"])

    outcome = run(installation, tmp_path, agent.runtime)

    assert outcome == FixOutcome(change=name)
    assert len(agent.runtime.requests) == 2
    assert "deterministic" in refusal_of(agent.runtime.requests[1])


def test_a_task_that_still_only_reruns_the_test_is_held_for_a_person(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, RERUNS["rerun"])

    outcome = run(installation, tmp_path, agent.runtime)

    assert len(agent.runtime.requests) == 2
    assert outcome.change == name
    assert outcome.held
    assert "deterministic" in outcome.reason
