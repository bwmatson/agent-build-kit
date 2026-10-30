"""A failed run is waited on before any rerun only when an open change fixes every failed test:
a test with no fix is rerun and checked on the base, and is never dropped behind the covered ones.
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
from tests.pipeline.test_flake_isolation import HookedProfile

COVERED = "tests/far/test_one.py::test_one"
MINE = "tests/far/test_two.py::test_two"


class Runs:
    """Lint passes, and every run, whole or by identifier, in the unit's checkout or on the base,
    fails on both tests except that `MINE` passes on the base."""

    def __init__(self, repo: Path) -> None:
        self.repo = repo
        self.ran: list[list[str]] = []

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        if command == ["lint"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        self.ran.append(command)
        failed = {COVERED: "assert 1 == 2", MINE: "assert 3 == 4"}
        if Path(str(kwargs["cwd"])) != self.repo:
            failed.pop(MINE)
        output = pytest_output(failed=failed, passed=() if failed else (MINE,))
        return subprocess.CompletedProcess(command, 1 if failed else 0, output, "")


def test_a_failure_with_no_fix_is_not_dropped_behind_a_covered_one(tmp_path: Path) -> None:
    installation: Installation = make_installation(tmp_path / "planning")
    (installation.changes_dir / fix_change_name(COVERED, "fix-test")).mkdir(parents=True)
    repo, base = branch(tmp_path, {})
    runs = Runs(repo)
    run = build_unit_test(
        profile=cast(ToolchainProfile, HookedProfile()), run=runs, changed=lambda *a: ["src/app.py"]
    )

    try:
        passed, message = run(cwd=repo, base=base)
    except FailedOnBase as found:
        pytest.fail(f"raised for {[failure.test for failure in found.failures]} only")

    assert not passed
    assert MINE in message
