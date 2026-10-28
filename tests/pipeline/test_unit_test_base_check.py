"""A failed unit-test test the unit did not write is run on the unit's own base (spec:
regression-agent).

The checkout is a real git repository and the runner is the faked boundary: it answers the
unit's commands and the base run with recorded-shape pytest output. A test that fails alone
and passes on the base is the unit's; one that fails on the base too is not, and a test
that fails by its time limit alone is not either.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import cast

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import FailedOnBase, fix_change_name
from agent_build_kit.pipeline.wiring import build_unit_test
from agent_build_kit.profiles.base import ToolchainProfile
from tests.conftest import make_installation
from tests.e2e_base_fakes import branch, pytest_output
from tests.factories import git
from tests.pipeline.test_flake_isolation import HookedProfile

TEST = "tests/far/test_one.py::test_one"
REASON = "assert 1 == 2"
TIMEOUT = "Failed: Timeout >60.0s"


class Runs:
    """Lint passes, the parallel run fails on the test, and every run of the test by its
    identifier fails in the unit's checkout (`alone`) and exits `on_base` in any other tree."""

    def __init__(self, repo: Path, *, reason: str = REASON, on_base: int = 1) -> None:
        self.repo, self.reason, self.on_base = repo, reason, on_base
        self.in_unit: list[list[str]] = []
        self.in_base: list[list[str]] = []
        # What each base run saw checked out, read as it ran: the tree is gone afterwards.
        self.heads: list[str] = []

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        cwd = Path(str(kwargs["cwd"]))
        if command == ["lint"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        failing = pytest_output(failed={TEST: self.reason})
        if not any("::" in argument for argument in command):
            return subprocess.CompletedProcess(command, 1, failing, "")
        if cwd == self.repo:
            self.in_unit.append(command)
            return subprocess.CompletedProcess(command, 1, failing, "")
        self.in_base.append(command)
        self.heads.append(git(cwd, "rev-parse", "HEAD").strip())
        output = failing if self.on_base else pytest_output(passed=(TEST,))
        return subprocess.CompletedProcess(command, self.on_base, output, "")


def unit_test(repo: Path, base: str, runs: Runs, *, changed: list[str]) -> tuple[bool, str]:
    return build_unit_test(
        profile=cast(ToolchainProfile, HookedProfile()), run=runs, changed=lambda *a: changed
    )(cwd=repo, base=base)


@pytest.fixture(autouse=True)
def workspace(tmp_path: Path) -> Installation:
    return make_installation(tmp_path / "planning")


def test_a_test_that_passes_on_the_base_stays_the_units_failure(tmp_path: Path) -> None:
    repo, base = branch(tmp_path, {})
    runs = Runs(repo, on_base=0)

    passed, message = unit_test(repo, base, runs, changed=["src/app.py"])

    assert not passed
    assert TEST in message
    assert len(runs.in_base) == 1, "it was run on the base"
    assert runs.heads == [base]


def test_a_test_that_fails_on_the_base_too_is_not_the_units(tmp_path: Path) -> None:
    repo, base = branch(tmp_path, {})
    runs = Runs(repo)

    with pytest.raises(FailedOnBase) as found:
        unit_test(repo, base, runs, changed=["src/app.py"])

    assert [failure.test for failure in found.value.failures] == [TEST]
    assert found.value.failures[0].output, "the failure's output goes to the agent"
    assert runs.heads == [base]


def test_the_base_is_the_ref_the_unit_ran_against_and_not_its_own_tip(tmp_path: Path) -> None:
    repo, base = branch(tmp_path, {})
    git(repo, "commit", "-qm", "later", "--allow-empty")
    tip = git(repo, "rev-parse", "HEAD").strip()
    runs = Runs(repo, on_base=0)

    unit_test(repo, base, runs, changed=["src/app.py"])

    assert runs.heads == [base] and base != tip


def test_the_base_run_leaves_no_worktree_behind(tmp_path: Path) -> None:
    repo, base = branch(tmp_path, {})

    with pytest.raises(FailedOnBase):
        unit_test(repo, base, Runs(repo), changed=["src/app.py"])

    assert len(git(repo, "worktree", "list").splitlines()) == 1


def test_a_time_limit_failure_that_fails_alone_is_recorded_for_a_fix_and_the_unit_waits(
    tmp_path: Path,
) -> None:
    repo, base = branch(tmp_path, {})
    # It would pass on the base: the time limit is what failed, so the base is not asked.
    runs = Runs(repo, reason=TIMEOUT, on_base=0)

    with pytest.raises(FailedOnBase) as found:
        unit_test(repo, base, runs, changed=["src/app.py"])

    assert [failure.test for failure in found.value.failures] == [TEST]
    assert TIMEOUT in found.value.failures[0].output
    assert len(runs.in_unit) == 2, "it was run alone, twice, as every failure is"


@pytest.mark.parametrize("prefix", ["fix-test", "fix-flaky", "fix-failing"])
def test_a_failing_test_with_an_open_fix_is_waited_on_before_any_rerun(
    tmp_path: Path, workspace: Installation, prefix: str
) -> None:
    (workspace.changes_dir / fix_change_name(TEST, prefix)).mkdir(parents=True)
    repo, base = branch(tmp_path, {})
    runs = Runs(repo, on_base=0)

    with pytest.raises(FailedOnBase) as found:
        unit_test(repo, base, runs, changed=["src/app.py"])

    assert [failure.test for failure in found.value.failures] == [TEST]
    assert runs.in_unit == [] and runs.in_base == [], "nothing was run again"
