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

from agent_build_kit.config import ProjectConfig
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import FailedOnBase, fix_change_name
from agent_build_kit.pipeline.wiring import build_unit_test, build_unit_test_base_check
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


# The base check of a saved failure: the failed tests that fail on the base, found from output.

OTHER = "tests/far/test_two.py::test_two"
PROJECT_TEST = "tests/test_a.py::test_a"


class BaseRuns:
    """Answers each run of tests by id as the process would: a test in `red` fails and any other
    passes, wherever it runs. What ran, where, is kept."""

    def __init__(self, *, red: tuple[str, ...]) -> None:
        self.red = red
        self.ran: list[tuple[Path, list[str]]] = []

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        ids = [argument for argument in command if "::" in argument]
        self.ran.append((Path(str(kwargs["cwd"])), ids))
        failed = {test: REASON for test in ids if test in self.red}
        passed = tuple(test for test in ids if test not in self.red)
        output = pytest_output(failed=failed, passed=passed)
        return subprocess.CompletedProcess(command, 1 if failed else 0, output, "")

    @property
    def ids(self) -> list[str]:
        return [test for _, ids in self.ran for test in ids]


def base_check(
    repo: Path,
    base: str,
    runs: BaseRuns,
    failed_output: str,
    *,
    changed: list[str],
    projects: list[ProjectConfig] | None = None,
) -> list[str]:
    return build_unit_test_base_check(
        profile=cast(ToolchainProfile, HookedProfile()),
        run=runs,
        changed=lambda *a: changed,
        projects=projects,
    )(cwd=repo, base=base, failed_output=failed_output)


def test_the_base_check_answers_the_failed_tests_that_fail_on_the_base_and_not_those_that_pass(
    tmp_path: Path,
) -> None:
    repo, base = branch(tmp_path, {})
    runs = BaseRuns(red=(TEST,))
    output = pytest_output(failed={TEST: REASON, OTHER: REASON})

    found = base_check(repo, base, runs, output, changed=["src/app.py"])

    assert found == [TEST]
    assert set(runs.ids) == {TEST, OTHER}, "each failed test was run on the base"


@pytest.mark.parametrize("written", ["tests/far/test_one.py", "tests/far/conftest.py"])
def test_a_test_whose_file_or_conftest_the_unit_changed_is_not_run_on_the_base(
    tmp_path: Path, written: str
) -> None:
    repo, base = branch(tmp_path, {})
    runs = BaseRuns(red=(TEST, OTHER))
    output = pytest_output(failed={TEST: REASON})

    found = base_check(repo, base, runs, output, changed=[written])

    assert found == []
    assert runs.ran == [], "nothing was run on the base"


def test_an_output_that_names_no_test_runs_nothing_on_the_base_and_answers_none(
    tmp_path: Path,
) -> None:
    repo, base = branch(tmp_path, {})
    runs = BaseRuns(red=(TEST,))

    found = base_check(repo, base, runs, "ruff.....Failed\n- hook id: ruff\n", changed=["a.py"])

    assert found == []
    assert runs.ran == []


def test_a_base_worktree_that_cannot_be_made_answers_none(tmp_path: Path) -> None:
    repo, _ = branch(tmp_path, {})
    runs = BaseRuns(red=(TEST,))

    found = base_check(
        repo, "no-such-ref", runs, pytest_output(failed={TEST: REASON}), changed=["src/app.py"]
    )

    assert found == []
    assert runs.ran == []


def test_the_ids_of_a_project_are_run_in_that_projects_folder_of_the_base_worktree(
    tmp_path: Path,
) -> None:
    repo, base = branch(tmp_path, {}, base_files={"svc/tests/test_a.py": "def test_a(): ...\n"})
    runs = BaseRuns(red=(PROJECT_TEST,))
    header = f"$ pytest (exit 1)\n(in {repo / 'svc'})\n"
    output = header + pytest_output(failed={PROJECT_TEST: REASON})

    found = base_check(
        repo, base, runs, output, changed=["src/app.py"], projects=[ProjectConfig(path="svc")]
    )

    assert found == [PROJECT_TEST]
    [(where, _)] = runs.ran
    assert where.name == "svc" and where != repo / "svc", "in the base's copy of the project"
