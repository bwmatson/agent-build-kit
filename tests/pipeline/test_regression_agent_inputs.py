"""What the agent's change names and what it is told: the failing test the kit reproduces when
the change is built, the earlier failures of both kinds of record, and the way a run the cap held
back is counted (spec: regression-agent)."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import fix_change_test, flake_record, next_fix_name
from agent_build_kit.pipeline.regression_agent import (
    FAILING_TEST_LABEL,
    FixOutcome,
    RegressionRunCapped,
    meet_all,
)
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.untouched_failures import preexisting_record
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.pipeline.test_flake_fix_change import change_with_unit, flaked
from tests.regression_agent_fakes import DefaultAgent, waited_on
from tests.regression_agent_support import PROPOSAL, TEST, Attempts, run, write_change
from tests.untouched_failure_fakes import failing

NAMED = "- Failing test: {test}\n"
OTHER = "tests/far/test_other.py::test_other"


def test_a_change_in_the_shape_the_agent_writes_names_its_test(installation: Installation) -> None:
    write_change(installation.changes_dir / "fix-test-x")

    assert fix_change_test(installation, "fix-test-x") == TEST


def test_a_change_of_another_test_is_read_as_that_test(installation: Installation) -> None:
    write_change(installation.changes_dir / "fix-test-y", test=OTHER)

    assert fix_change_test(installation, "fix-test-y") == OTHER


@pytest.mark.parametrize("line", ["", f"- Failing test: {OTHER}\n"], ids=["none", "another-test"])
def test_a_change_that_does_not_name_the_failing_test_is_refused_and_rewritten_once(
    installation: Installation, tmp_path: Path, line: str
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, {"proposal": PROPOSAL.replace(NAMED, line)}, {})

    outcome = run(installation, tmp_path, agent.runtime)

    assert outcome == FixOutcome(change=name)
    assert len(agent.runtime.requests) == 2
    assert FAILING_TEST_LABEL in agent.runtime.requests[1].prompt


def test_a_change_that_still_names_no_test_is_held(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, {"proposal": PROPOSAL.replace(NAMED, "")})

    outcome = run(installation, tmp_path, agent.runtime)

    assert outcome.held and FAILING_TEST_LABEL in outcome.reason


def test_the_prompt_asks_for_the_failing_test_line(
    installation: Installation, tmp_path: Path
) -> None:
    agent = Attempts(installation, next_fix_name(installation, TEST), {})

    run(installation, tmp_path, agent.runtime)

    assert f"`{FAILING_TEST_LABEL} {TEST}`" in agent.runtime.request.prompt


# --- the earlier failures of both records ----------------------------------------------


def test_the_failures_of_both_records_are_in_the_prompt_oldest_first(
    installation: Installation, no_real_regression_agent: DefaultAgent
) -> None:
    unit = change_with_unit(installation, "feature", "feature/1")
    early = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
    late = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    preexisting_record(installation).append(
        failing(TEST, unit="older/9").model_copy(update={"at": late})
    )
    flake_record(installation).append(flaked(TEST, unit="older/3").model_copy(update={"at": early}))

    waited_on(installation, flaked(), unit)

    prompt = no_real_regression_agent.runtime.request.prompt
    assert "older/3" in prompt and "older/9" in prompt
    assert prompt.index("older/3") < prompt.index("older/9")


# --- how a run the cap held back is counted -------------------------------------------


def capped() -> str | None:
    raise RegressionRunCapped("tests/x.py::test_x", 1)


def test_meet_all_makes_every_call_and_says_which_the_cap_held_back() -> None:
    met = meet_all([lambda: "fix-a", capped, lambda: None, lambda: "fix-b"])

    assert met.answers == ["fix-a", None, None, "fix-b"]
    assert met.held_back == [False, True, False, False]
    assert met.capped and "max_regression_runs_per_hour" in met.note


def test_a_failure_the_cap_held_back_does_not_count_against_the_unit_but_another_one_does() -> None:
    assert meet_all([lambda: "fix-a", capped]).all_answered
    assert not meet_all([lambda: "fix-a", lambda: None, capped]).all_answered
    assert meet_all([]).all_answered and not meet_all([]).capped


# --- the wording of `abk status` -------------------------------------------------------


def status_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    **row: str,
) -> str:
    workspace = make_installation(
        tmp_path, planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees"))
    )
    UnitStore(tmp_path / "units.json").upsert([stored_unit("one/1", change="one")])
    flake_record(workspace).append(
        flaked(TEST, "one/1").model_copy(update={"failing": True, "change": "fix-test-x", **row})
    )
    monkeypatch.setattr(cli, "current_usage", lambda: None)

    assert cli.cmd_status(argparse.Namespace(), workspace) == 0

    (line,) = [found for found in capsys.readouterr().out.splitlines() if TEST in found]
    return line


def test_status_says_on_its_base_only_for_a_failure_a_base_run_showed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    line = status_line(tmp_path, monkeypatch, capsys, base_output="FAILED on the base")

    assert "failed on its base 1 time" in line


def test_status_does_not_say_on_its_base_for_a_failure_never_run_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    line = status_line(tmp_path, monkeypatch, capsys)

    assert "failed 1 time" in line and "on its base" not in line
