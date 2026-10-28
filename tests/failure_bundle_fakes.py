"""A unit-test run that fails, as the processes answer it, for the tests of the failure bundle.

`BundleMachine` answers git, lint, the version query and the test run; the run itself removes one
file under `tests/` and adds another, as something else on the host might. A test run prints what
a `-q` run prints: no header. It runs in the `scratch` checkout of `tests/pipeline/conftest.py`.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit.profiles.python_uv import PythonUvProfile

RECORDED = Path(__file__).resolve().parent / "fixtures" / "external" / "pytest"
START = datetime(2026, 10, 11, 12, 0, 0, tzinfo=UTC)
# What `pytest --version --version` printed, as recorded: the profile queries it because a `-q`
# run prints no header.
VERSIONS = (RECORDED / "version_verbose.txt").read_text()


class BundleProfile(PythonUvProfile):
    """The python-uv profile with one lint command; its test commands are its own."""

    def lint_command(self, base: str) -> list[str]:
        return ["lint"]


class BundleMachine:
    """Git, lint, the version query and the test run as the processes answer."""

    def __init__(self, root: Path, *, reruns: list[int], passing: bool = False) -> None:
        self.root = root
        self.reruns = list(reruns)
        self.passing = passing
        self.status_calls = 0
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        self.commands.append(command)
        if command == ["lint"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:2] == ["git", "status"]:
            self.status_calls += 1
            return subprocess.CompletedProcess(
                command, 0, f" M src/file{self.status_calls}.py\n", ""
            )
        if command[:2] == ["git", "rev-parse"]:
            sha = "b" * 7 if command[-1] == "main" else "a" * 7
            return subprocess.CompletedProcess(command, 0, sha + "\n", "")
        if command[-2:] == ["--version", "--version"]:
            return subprocess.CompletedProcess(command, 0, VERSIONS, "")
        if any("::" in argument for argument in command):
            return subprocess.CompletedProcess(command, self.reruns.pop(0), "1 passed\n", "")
        if self.passing:
            return subprocess.CompletedProcess(command, 0, "5 passed in 0.03s\n", "")
        (self.root / "tests" / "test_gone.py").unlink(missing_ok=True)
        (self.root / "tests" / "test_new.py").write_text("")
        failure = (RECORDED / "console_failures.txt").read_text().split("\n", 1)[1]
        return subprocess.CompletedProcess(command, 1, failure, "")
