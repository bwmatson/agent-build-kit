"""The untouched tests that fail tier 2 are run once on the base, together, in a clean
worktree inside the unit's stack hold (spec: tier2-failures).

The checkout is a real git repository and the runner is the faked boundary: it answers the
unit's command and the base run with recorded-shape pytest output.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit.pipeline import wiring
from agent_build_kit.pipeline.tier2 import TestFailure
from agent_build_kit.profiles.python_uv import PROFILE, PythonUvProfile
from tests.factories import git
from tests.tier2_base_fakes import TEST_BODY, Runs, branch, pytest_output, session

OWN = "tests/live/test_own.py::test_route"
ONE = "tests/far/test_one.py::test_one"
TWO = "tests/far/test_two.py::test_two"
THREE = "tests/far/test_three.py::test_three"
REASON = "assert 1 == 2"


def names_of(failures: list[TestFailure]) -> list[str]:
    return [failure.test for failure in failures]


def judged(tmp_path: Path, own: str, base: str):
    repo, base_sha = branch(tmp_path, {})
    runs = Runs(repo, own, base)
    gate = session(tmp_path, runs)
    gate.run(cwd=repo, base=base_sha)
    return gate, runs


def test_a_test_the_base_run_names_as_failed_or_errored_is_pre_existing(tmp_path: Path) -> None:
    own = pytest_output(failed={ONE: REASON, TWO: REASON})
    base = pytest_output(failed={ONE: REASON}, errored={TWO: "KeyError: 'PORT'"})

    gate, _ = judged(tmp_path, own, base)

    assert gate.verdict is not None
    assert names_of(gate.verdict.pre_existing) == [ONE, TWO]
    assert gate.verdict.broken == []
    assert gate.verdict.own == []


def test_a_test_that_passes_on_the_base_is_broken_by_the_unit(tmp_path: Path) -> None:
    own = pytest_output(failed={ONE: REASON, TWO: REASON})
    base = pytest_output(failed={ONE: REASON}, passed=(TWO,))

    gate, _ = judged(tmp_path, own, base)

    assert gate.verdict is not None
    assert names_of(gate.verdict.pre_existing) == [ONE]
    assert names_of(gate.verdict.broken) == [TWO]


def test_a_test_the_base_does_not_contain_or_name_is_broken_by_the_unit(tmp_path: Path) -> None:
    own = pytest_output(failed={ONE: REASON, TWO: REASON, THREE: REASON})
    # the base run names one, collects nothing for another, and says nothing of the third
    base = pytest_output(failed={ONE: REASON}) + f"ERROR: not found: {TWO}\n"

    gate, _ = judged(tmp_path, own, base)

    assert gate.verdict is not None
    assert names_of(gate.verdict.pre_existing) == [ONE]
    assert names_of(gate.verdict.broken) == [TWO, THREE]


def test_a_base_run_that_says_nothing_proves_nothing(tmp_path: Path) -> None:
    gate, _ = judged(tmp_path, pytest_output(failed={ONE: REASON}), "")

    assert gate.verdict is not None
    assert gate.verdict.pre_existing == []
    assert names_of(gate.verdict.broken) == [ONE]


def test_three_untouched_tests_make_one_command_run_once(tmp_path: Path) -> None:
    ids = [ONE, TWO, THREE]
    own = pytest_output(failed=dict.fromkeys(ids, REASON))

    _, runs = judged(tmp_path, own, own)

    assert len(runs.on_unit) == 1
    assert runs.on_base == [PROFILE.serial_rerun_command(runs.on_unit[0], ids)]


def test_a_unit_with_a_test_of_its_own_and_a_pre_existing_one_fails(tmp_path: Path) -> None:
    own = pytest_output(failed={OWN: REASON, ONE: REASON})
    base = pytest_output(failed={ONE: REASON})
    repo, base_sha = branch(tmp_path, {"tests/live/test_own.py": TEST_BODY})
    runs = Runs(repo, own, base)
    gate = session(tmp_path, runs)

    ok, _ = gate.run(cwd=repo, base=base_sha)

    assert not ok
    assert gate.verdict is not None
    assert names_of(gate.verdict.own) == [OWN]
    assert names_of(gate.verdict.pre_existing) == [ONE]
    assert gate.verdict.broken == []
    # only the untouched test is run on the base
    assert runs.on_base == [PROFILE.serial_rerun_command(runs.on_unit[0], [ONE])]


def test_the_base_run_is_in_a_detached_worktree_at_the_ref_the_unit_ran_against(
    tmp_path: Path,
) -> None:
    repo, base_sha = branch(tmp_path, {"tests/live/test_own.py": TEST_BODY})
    runs = Runs(repo, pytest_output(failed={ONE: REASON}), pytest_output(failed={ONE: REASON}))
    gate = session(tmp_path, runs)

    gate.run(cwd=repo, base=base_sha)

    assert len(runs.trees) == 1
    assert runs.trees[0] != repo
    assert runs.heads == [base_sha]
    assert not runs.trees[0].exists()
    assert len(git(repo, "worktree", "list").splitlines()) == 1


def test_a_base_run_that_raises_leaves_no_worktree_and_the_units_tree_unchanged(
    tmp_path: Path,
) -> None:
    repo, base_sha = branch(tmp_path, {"tests/live/test_own.py": TEST_BODY})
    head = git(repo, "rev-parse", "HEAD").strip()
    runs = Runs(repo, pytest_output(failed={ONE: REASON}), raises=OSError("stack went away"))
    gate = session(tmp_path, runs)

    ok, _ = gate.run(cwd=repo, base=base_sha)

    assert ok is False
    assert gate.verdict is not None
    assert names_of(gate.verdict.broken) == [ONE]
    assert gate.verdict.pre_existing == []
    assert len(runs.trees) == 1
    assert not runs.trees[0].exists()
    assert len(git(repo, "worktree", "list").splitlines()) == 1
    assert git(repo, "rev-parse", "HEAD").strip() == head
    assert git(repo, "status", "--porcelain").strip() == ""


def test_a_base_that_cannot_be_checked_out_leaves_the_unit_failing_as_before(
    tmp_path: Path,
) -> None:
    repo, _ = branch(tmp_path, {})
    runs = Runs(repo, pytest_output(failed={ONE: REASON}), pytest_output(failed={ONE: REASON}))
    gate = session(tmp_path, runs)

    ok, snapshot = gate.run(cwd=repo, base="0" * 40)

    assert ok is False
    assert ONE in snapshot
    assert gate.verdict is not None
    assert names_of(gate.verdict.broken) == [ONE]
    assert runs.on_base == []
    assert len(git(repo, "worktree", "list").splitlines()) == 1


def test_each_failed_command_is_repeated_on_the_base_with_its_own_tests(tmp_path: Path) -> None:
    first = ["uv", "run", "--directory", "a", "pytest", "-m", "local_stack"]
    second = ["uv", "run", "--directory", "b", "pytest", "-m", "local_stack"]

    class Members(PythonUvProfile):
        def tier2_commands(self, repo: Path, *, marker: str) -> list[list[str]]:
            return [first, second]

    repo, base_sha = branch(tmp_path, {})
    own = {
        tuple(first): pytest_output(passed=("tests/a/test_a.py::test_a",)),
        tuple(second): pytest_output(failed={ONE: REASON}),
    }
    runs = Runs(repo, own, pytest_output(failed={ONE: REASON}))
    gate = session(tmp_path, runs, profile=Members())

    gate.run(cwd=repo, base=base_sha)

    assert gate.verdict is not None
    assert names_of(gate.verdict.pre_existing) == [ONE]
    assert runs.on_base == [PROFILE.serial_rerun_command(second, [ONE])]


def test_the_stack_lock_is_taken_once_for_the_unit_run_and_the_base_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, base_sha = branch(tmp_path, {})
    own = pytest_output(failed={ONE: REASON})
    events: list[str] = []
    runs = Runs(repo, own, own, events=events)

    real = wiring.stack_lock

    @contextlib.contextmanager
    def watched(path: Path, timeout: float, setting: str | None = None) -> Iterator[None]:
        events.append("take")
        with real(path, timeout, setting):
            yield
        events.append("release")

    monkeypatch.setattr(wiring, "stack_lock", watched)
    gate = session(tmp_path, runs)

    gate.run(cwd=repo, base=base_sha)

    assert events == ["take", "unit", "base", "release"]
