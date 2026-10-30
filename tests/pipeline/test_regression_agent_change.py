"""The change the regression agent writes (spec: regression-agent).

The agent is a stand-in runtime whose action writes files into the change directory, as the real
one does; the planning repo and the code repo are folders under the test's temporary path.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from agent_build_kit.config import models
from agent_build_kit.hooks.policy import decide
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import flake_record, next_fix_name
from agent_build_kit.pipeline.regression_agent import FixKind, FixOutcome
from agent_build_kit.pipeline.work_graph import check_tags, declared_projects, declared_split_names
from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.base import AgentRateLimited
from tests.regression_agent_support import (
    BASE,
    BASE_OUTPUT,
    EVIDENCE,
    SPEC,
    TEST,
    UNDECIDED,
    Attempts,
    failure,
    run,
    writes,
)
from tests.runtimes.stand_in import StandInRuntime


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


def test_the_request_lets_the_hook_write_the_change_and_nothing_else_of_the_planning_repo(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, {})
    for checkout in (installation.root, tmp_path / "base-checkout"):
        checkout.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)

    run(installation, tmp_path, agent.runtime)

    request = agent.runtime.request
    assert request.policy is not None and request.policy.no_commit

    def answer(target: Path) -> dict | None:
        payload = {
            "tool_name": "Write",
            "cwd": str(request.cwd),
            "tool_input": {"file_path": str(target)},
        }
        return decide(
            payload,
            planning_repo=request.planning_repo,
            planning_change_dir=request.planning_change_dir,
            specs=request.policy.specs_dir,
            no_commit=request.policy.no_commit,
        )

    assert answer(installation.changes_dir / name / "proposal.md") is None
    assert answer(installation.changes_dir / "other" / "tasks.md") is not None
    assert answer(tmp_path / "base-checkout" / "src" / "x.py") is not None, "the base is read-only"
    assert any(installation.changes_dir.is_relative_to(path) for path in request.add_dirs)


def test_a_delta_spec_openspec_refuses_is_sent_back_once_and_then_held(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    unscened = SPEC.replace("#### Scenario:", "#### Case:")

    fixed = Attempts(installation, name, {"spec": unscened}, {})
    assert run(installation, tmp_path, fixed.runtime) == FixOutcome(change=name)
    assert len(fixed.runtime.requests) == 2
    assert "no scenario" in fixed.runtime.requests[1].prompt

    shutil.rmtree(installation.changes_dir / name)
    stuck = Attempts(installation, name, {"spec": unscened})
    outcome = run(installation, tmp_path, stuck.runtime)
    assert len(stuck.runtime.requests) == 2
    assert outcome.held and "no scenario" in outcome.reason


def test_a_change_the_check_accepts_passes_abk_tags(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, {})

    outcome = run(installation, tmp_path, agent.runtime)

    _, errors = check_tags(
        name,
        installation.changes_dir,
        repos=tuple(installation.repos),
        projects=declared_projects(installation.repos),
        splits=declared_split_names(installation.repos, installation.config),
    )
    assert not outcome.held
    assert errors == []


def test_a_group_after_the_acceptance_group_is_sent_back(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    late = (
        "# Tasks\n\nPriority: 1\n\n"
        "## 1. [app] [unit-test] [contract] Read the label\n\n- [ ] 1.1 Read it.\n\n"
        "## 2. [app] [e2e-test] [acceptance] Drive it\n\n- [ ] 2.1 Drive it.\n\n"
        "## 3. [app] [unit-test] Late work\n\n- [ ] 3.1 Do it.\n"
    )
    agent = Attempts(installation, name, {"tasks": late}, {})

    outcome = run(installation, tmp_path, agent.runtime)

    assert len(agent.runtime.requests) == 2
    assert "comes after the [acceptance] group" in agent.runtime.requests[1].prompt
    assert outcome == FixOutcome(change=name)


def test_a_run_that_failed_is_held_with_its_error_and_not_run_again(
    installation: Installation, tmp_path: Path
) -> None:
    runtime = StandInRuntime(ok=False, error="the agent exited 1")

    outcome = run(installation, tmp_path, runtime)

    assert len(runtime.requests) == 1
    assert outcome.held
    assert "the agent exited 1" in outcome.reason


def test_a_runtime_that_raises_leaves_no_empty_change_directory(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)

    def limited(request: AgentRequest) -> None:
        raise AgentRateLimited("usage limit reached")

    with pytest.raises(AgentRateLimited):
        run(installation, tmp_path, StandInRuntime(act=limited))

    assert not (installation.changes_dir / name).exists()


def test_a_change_with_tasks_already_open_is_answered_without_a_run(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    writes(installation, name, flag="")
    runtime = StandInRuntime()

    outcome = run(installation, tmp_path, runtime)

    assert outcome == FixOutcome(change=name)
    assert runtime.requests == []
    assert "[contract]" not in (installation.changes_dir / name / "tasks.md").read_text()


def test_two_units_meeting_one_test_share_one_change(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, {})

    first = run(installation, tmp_path, agent.runtime)
    second = run(installation, tmp_path, agent.runtime)

    assert first.change == second.change == name
    assert len(agent.runtime.requests) == 1
