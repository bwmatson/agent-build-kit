"""The python profile reads the markers its test runner registers, for `abk e2e-test check`
(spec: e2e-splits)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from agent_build_kit.profiles.python_uv import PROFILE

MARKERS = (
    "@pytest.mark.local_stack: tests that need the live stack\n\n"
    "@pytest.mark.runtime_acp: needs the acp runtime\n\n"
    "@pytest.mark.timeout(timeout, method=None): a timeout\n\n"
    "@pytest.mark.parametrize(argnames, argvalues): run with several sets\n"
)


class Runner:
    def __init__(self, stdout: str, returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        self.commands.append(command)
        return subprocess.CompletedProcess(command, self.returncode, self.stdout, "")


def test_the_registered_selectors_are_the_runners_marker_names() -> None:
    run = Runner(MARKERS)

    found = PROFILE.registered_selectors(["uv", "run", "pytest", "-m", "local_stack"], run=run)

    assert found is not None
    assert {"local_stack", "runtime_acp", "timeout", "parametrize"} <= set(found)
    assert "runtime_claude_code" not in found
    (listed,) = run.commands
    assert "--markers" in listed


def test_a_failed_marker_listing_is_unknown_not_an_empty_list() -> None:
    run = Runner("ERROR: usage\n", returncode=4)

    assert PROFILE.registered_selectors(["uv", "run", "pytest"], run=run) is None


def test_a_marker_the_runner_registers_is_listed_by_a_real_pytest(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\nmarkers = ["local_stack", "runtime_acp"]\n'
    )

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        return subprocess.run(argv, cwd=tmp_path, **kwargs)

    found = PROFILE.registered_selectors([sys.executable, "-m", "pytest"], run=run)

    assert found is not None
    assert {"local_stack", "runtime_acp"} <= set(found)
    assert "runtime_claude_code" not in found
