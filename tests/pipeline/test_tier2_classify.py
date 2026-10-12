"""A failed tier 2 test is the unit's own when its file is one the branch changed, and
untouched otherwise (spec: tier2-failures). Nothing is run to say so."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.tier2 import TestFailure, Tier2Classification
from agent_build_kit.profiles.python_uv import PythonUvProfile
from tests.tier2_base_fakes import (
    TEST_BODY,
    Runs,
    branch,
    pytest_output,
    result_of,
    session,
)

OWN = "tests/live/test_own.py::test_route"
FAR = "tests/far/test_far.py::test_far"
BESIDE = "tests/live/test_beside.py::test_beside"


def classified(tmp_path: Path, changed: dict[str, str], *tests: str) -> Tier2Classification:
    repo, base = branch(tmp_path, changed, base_files={"tests/live/test_beside.py": TEST_BODY})
    runs = Runs(repo, "")
    gate = session(tmp_path, runs)
    gate.result = result_of(*tests)

    found = gate.classify(cwd=repo, base=base)

    assert runs.calls == []
    return found


def names_of(failures: list[TestFailure]) -> list[str]:
    return [failure.test for failure in failures]


def test_a_failure_in_a_file_the_branch_changed_is_the_units_own(tmp_path: Path) -> None:
    found = classified(tmp_path, {"tests/live/test_own.py": TEST_BODY}, OWN)

    assert names_of(found.own) == [OWN]
    assert found.untouched == []


def test_a_failure_in_an_untouched_file_is_untouched(tmp_path: Path) -> None:
    found = classified(tmp_path, {"tests/live/test_own.py": TEST_BODY}, FAR, OWN)

    assert names_of(found.untouched) == [FAR]
    assert names_of(found.own) == [OWN]


def test_a_test_file_beside_a_changed_conftest_is_the_units_own(tmp_path: Path) -> None:
    found = classified(tmp_path, {"tests/live/conftest.py": "import pytest\n"}, BESIDE, FAR)

    assert names_of(found.own) == [BESIDE]
    assert names_of(found.untouched) == [FAR]


def test_a_failure_with_no_readable_ids_classifies_nothing(tmp_path: Path) -> None:
    repo, base = branch(tmp_path, {})
    runs = Runs(repo, "Error: the stack did not come up\n")
    gate = session(tmp_path, runs)

    ok, _ = gate.run(cwd=repo, base=base)

    assert not ok
    assert gate.classify(cwd=repo, base=base) == Tier2Classification()
    assert gate.verdict is None
    assert runs.on_base == []


def test_a_profile_without_the_hook_classifies_nothing(tmp_path: Path) -> None:
    class NoHook(PythonUvProfile):
        def parse_test_failures(self, output: str) -> list[TestFailure]:
            return []

    repo, base = branch(tmp_path, {})
    runs = Runs(repo, pytest_output(failed={FAR: "assert 1 == 2"}))
    gate = session(tmp_path, runs, profile=NoHook())

    gate.run(cwd=repo, base=base)

    assert gate.classify(cwd=repo, base=base) == Tier2Classification()
    assert runs.on_base == []


def test_a_dev_stack_run_classifies_nothing(tmp_path: Path) -> None:
    repo, base = branch(tmp_path, {})
    script = repo / "scripts" / "dev-stack.sh"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\n")
    runs = Runs(repo, pytest_output(failed={FAR: "assert 1 == 2"}))
    gate = session(tmp_path, runs)

    ok, _ = gate.run(cwd=repo, base=base)

    assert not ok
    assert gate.result is not None and gate.result.failures
    assert gate.classify(cwd=repo, base=base) == Tier2Classification()
    assert gate.verdict is None
    assert runs.on_base == []
