"""A fix change for test code says which files its group names (spec: regression-agent): the prompt
asks for a `Paths:` line, the refusal of a group that is not `tests_only` names the line to write,
and the kit writes the line itself where the group names test files and nothing but symbol names
(a backticked name with a dot reads as a source path). The agent is a stand-in that writes a
canned change; no model runs.
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

# A task of a cause in test code that names the test file and two symbols, which the floor reads
# as source paths.
WITH_SYMBOLS = (
    "In `tests/test_widget.py`, set SIGINT to `signal.default_int_handler` for the test and "
    "pair each call of `Recording.complete_json` with its page text."
)
WITH_A_SOURCE_FILE = f"{WITH_SYMBOLS} Read the label in `src/widget.py`."
TEST_CODE = {"tasks": group_tasks(WITH_SYMBOLS), "proposal": proposal_for_test_code()}
PATHS_LINE = "Paths: `tests/test_widget.py`"


def written_tasks(inst: Installation, name: str) -> str:
    return (inst.changes_dir / name / "tasks.md").read_text()


def tags_of(inst: Installation, name: str, capsys: pytest.CaptureFixture[str]) -> str:
    """The first group line `abk tags` prints for the change `name`."""
    cli.cmd_tags(argparse.Namespace(all=False, change=name), inst)
    out = capsys.readouterr().out.splitlines()
    return next(line for line in out if line.strip().startswith("1."))


def test_the_prompt_asks_for_a_paths_line_and_says_why(
    installation: Installation, tmp_path: Path
) -> None:
    agent = Attempts(installation, next_fix_name(installation, TEST), TEST_CODE)

    run(installation, tmp_path, agent.runtime)

    prompt = agent.runtime.requests[0].prompt
    assert "`Paths:`" in prompt
    assert "name with a dot" in prompt


def test_a_group_naming_the_test_file_and_symbols_gets_the_line_and_is_accepted(
    installation: Installation, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, TEST_CODE)

    outcome = run(installation, tmp_path, agent.runtime)

    tasks = written_tasks(installation, name)
    assert outcome == FixOutcome(change=name)
    assert len(agent.runtime.requests) == 1
    assert tasks.count(PATHS_LINE) == 1
    assert tasks.index(PATHS_LINE) < tasks.index("- [ ] 1.1")
    assert "tests_only" in tags_of(installation, name, capsys)


def test_the_line_the_kit_wrote_is_said_in_the_log(
    installation: Installation, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    agent = Attempts(installation, next_fix_name(installation, TEST), TEST_CODE)

    run(installation, tmp_path, agent.runtime)

    assert f"group 1 gets {PATHS_LINE}" in capsys.readouterr().out


def test_a_group_that_also_names_a_source_file_is_left_as_written_and_refused_with_the_remedy(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(
        installation,
        name,
        {**TEST_CODE, "tasks": group_tasks(WITH_A_SOURCE_FILE)},
    )

    outcome = run(installation, tmp_path, agent.runtime)

    assert outcome.held
    assert "Paths:" not in written_tasks(installation, name)
    assert len(agent.runtime.requests) == 2
    assert "Paths: <the test files the group names>" in refusal_of(agent.runtime.requests[1])


def test_a_group_that_already_has_a_paths_line_is_not_given_another(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(
        installation,
        name,
        {**TEST_CODE, "tasks": group_tasks(WITH_SYMBOLS, header=f"{PATHS_LINE}\n")},
    )

    outcome = run(installation, tmp_path, agent.runtime)

    assert outcome == FixOutcome(change=name)
    assert written_tasks(installation, name).count("Paths:") == 1


def test_a_cause_in_source_gets_no_line(installation: Installation, tmp_path: Path) -> None:
    name = next_fix_name(installation, TEST)
    tasks = group_tasks(f"Test: with a fake clock, {WITH_SYMBOLS}", FIX_THE_SOURCE)
    agent = Attempts(installation, name, {"tasks": tasks, "proposal": PROPOSAL})

    run(installation, tmp_path, agent.runtime)

    assert "Paths:" not in written_tasks(installation, name)


def test_an_e2e_group_gets_no_line(installation: Installation, tmp_path: Path) -> None:
    name = next_fix_name(installation, TEST)
    tasks = group_tasks(WITH_SYMBOLS).replace("[unit-test]", "[e2e-test]")
    agent = Attempts(installation, name, {**TEST_CODE, "tasks": tasks})

    run(installation, tmp_path, agent.runtime)

    assert "Paths:" not in written_tasks(installation, name)


def test_a_group_that_names_only_the_test_file_is_not_touched(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, {**TEST_CODE, "tasks": group_tasks(FIX_THE_TEST)})

    outcome = run(installation, tmp_path, agent.runtime)

    assert outcome == FixOutcome(change=name)
    assert "Paths:" not in written_tasks(installation, name)
