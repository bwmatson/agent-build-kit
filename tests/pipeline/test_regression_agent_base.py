"""The agent reads the tree the test failed on, and the base run's own output (spec:
regression-agent).

A stacked unit's base is its parent's branch tip, and the failure carries that ref from the run
that found it; the agent runs in a detached worktree of it. The base run's output rides on the
failure and reaches the prompt under the base heading; a failure by the time limit alone was
never run on the base, so it has none.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import cast

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import FailedOnBase, Flake
from agent_build_kit.pipeline.regression_agent import FixKind, wait_on_regression
from agent_build_kit.pipeline.wiring import build_unit_test
from agent_build_kit.profiles.base import ToolchainProfile
from agent_build_kit.runtimes import AgentRequest
from tests.e2e_base_fakes import branch, pytest_output
from tests.factories import commit, git, init_repo, stored_unit
from tests.pipeline.test_flake_isolation import HookedProfile
from tests.pipeline.test_unit_test_base_check import REASON, TEST, TIMEOUT
from tests.regression_agent_fakes import DefaultAgent
from tests.regression_agent_support import failure

BASE_HEADING = "Output of the same test on the base"
BASE_REASON = "assert on_the_base == 2"


class Runs:
    """The unit's checkout fails the test with `REASON`; any other tree fails it with the base's
    own reason, or passes it with `on_base` 0."""

    def __init__(self, repo: Path, *, reason: str = REASON, on_base: int = 1) -> None:
        self.repo, self.reason, self.on_base = repo, reason, on_base

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        cwd = Path(str(kwargs["cwd"]))
        if command == ["lint"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        failing = pytest_output(failed={TEST: self.reason})
        if not any("::" in argument for argument in command) or cwd == self.repo:
            return subprocess.CompletedProcess(command, 1, failing, "")
        output = pytest_output(failed={TEST: BASE_REASON}) if self.on_base else failing
        return subprocess.CompletedProcess(command, self.on_base, output, "")


def failed_on_base(repo: Path, base: str, runs: Runs) -> Flake:
    try:
        build_unit_test(
            profile=cast(ToolchainProfile, HookedProfile()),
            run=runs,
            changed=lambda *a: ["src/app.py"],
        )(cwd=repo, base=base)
    except FailedOnBase as found:
        return found.failures[0]
    raise AssertionError("unit-test did not raise FailedOnBase")


def asked(installation: Installation, flake: Flake) -> AgentRequest:
    """The request the agent is given for `flake`, met by a unit of the `app` repo."""
    agent = DefaultAgent()
    wait_on_regression(
        installation,
        flake,
        stored_unit("feature/1", change="feature", groups=(1,)),
        kind=FixKind.REGRESSION,
        runtime=agent.runtime,
        base_output=flake.base_output,
        wait=False,
        say=lambda message: None,
    )
    return agent.runtime.request


def test_a_failure_on_the_base_carries_the_ref_and_the_base_runs_output(
    installation: Installation, tmp_path: Path
) -> None:
    repo, base = branch(tmp_path / "code", {})

    flake = failed_on_base(repo, base, Runs(repo))

    assert flake.base == base
    assert BASE_REASON in flake.base_output
    assert REASON not in flake.base_output, "not the unit's own run"


def test_a_failure_by_its_time_limit_alone_has_no_base_output(
    installation: Installation, tmp_path: Path
) -> None:
    repo, base = branch(tmp_path / "code", {})

    flake = failed_on_base(repo, base, Runs(repo, reason=TIMEOUT, on_base=0))

    assert flake.base == base
    assert flake.base_output == ""


def test_the_prompt_prints_the_base_runs_output_under_the_base_heading(
    installation: Installation, tmp_path: Path
) -> None:
    repo, base = branch(tmp_path / "code", {})

    request = asked(installation, failed_on_base(repo, base, Runs(repo)))

    heading = request.prompt.index(BASE_HEADING)
    assert BASE_REASON in request.prompt[heading:]
    assert BASE_REASON not in request.prompt[:heading], "the base's text is not the failing run's"


def test_a_failure_by_its_time_limit_alone_prints_no_base_heading(
    installation: Installation, tmp_path: Path
) -> None:
    repo, base = branch(tmp_path / "code", {})

    request = asked(installation, failed_on_base(repo, base, Runs(repo, reason=TIMEOUT, on_base=0)))

    assert BASE_HEADING not in request.prompt


def stacked(installation: Installation) -> tuple[Path, str]:
    """The `app` checkout, with a parent's branch one commit ahead of `main`: the checkout and
    the parent's tip."""
    checkout = init_repo(installation.checkouts["app"])
    commit(checkout, "a.txt")
    git(checkout, "switch", "-q", "-c", "spec/parent/1")
    tip = commit(checkout, "parent.txt").strip()
    git(checkout, "switch", "-q", "main")
    return checkout, tip


def ran_looking(
    installation: Installation, flake: Flake
) -> tuple[DefaultAgent, list[tuple[Path, str]]]:
    """The agent step run for `flake`, with where the agent worked and what that tree held read as
    it ran: the worktree is gone when the run is over."""
    seen: list[tuple[Path, str]] = []
    agent = DefaultAgent()
    act = agent.runtime.act

    def look(request: AgentRequest) -> None:
        assert request.cwd is not None
        seen.append((request.cwd, git(request.cwd, "rev-parse", "HEAD").strip()))
        assert act is not None
        act(request)

    agent.runtime.act = look
    wait_on_regression(
        installation,
        flake,
        stored_unit("feature/1", change="feature", groups=(1,)),
        kind=FixKind.REGRESSION,
        runtime=agent.runtime,
        wait=False,
        say=lambda message: None,
    )
    return agent, seen


def test_a_stacked_units_agent_runs_in_a_worktree_of_its_parents_tip(
    installation: Installation,
) -> None:
    checkout, tip = stacked(installation)

    agent, seen = ran_looking(installation, failure(base="spec/parent/1"))

    ((cwd, head),) = seen
    assert cwd != checkout and head == tip
    assert "spec/parent/1" in agent.runtime.request.prompt
    assert len(git(checkout, "worktree", "list").splitlines()) == 1, "the worktree was removed"


def test_a_failure_with_no_base_ref_runs_the_agent_in_a_worktree_of_the_default_branch(
    installation: Installation,
) -> None:
    checkout, _ = stacked(installation)
    trunk = git(checkout, "rev-parse", "main").strip()

    agent, seen = ran_looking(installation, failure())

    ((cwd, head),) = seen
    assert cwd != checkout and head == trunk, "a scheduled run, say, names no base"
    assert "main" in agent.runtime.request.prompt
    assert len(git(checkout, "worktree", "list").splitlines()) == 1, "the worktree was removed"


def test_a_worktree_that_cannot_be_made_leaves_the_agent_in_the_checkout(
    installation: Installation,
) -> None:
    # The checkout is no git repository: there is nothing to make a worktree of.
    checkout = installation.checkouts["app"]
    checkout.mkdir(parents=True)
    agent = DefaultAgent()

    wait_on_regression(
        installation,
        failure(),
        stored_unit("feature/1", change="feature", groups=(1,)),
        kind=FixKind.REGRESSION,
        runtime=agent.runtime,
        wait=False,
        say=lambda message: None,
    )

    assert agent.runtime.request.cwd == checkout
