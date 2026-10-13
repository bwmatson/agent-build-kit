"""Stand-ins for the tier 1 runner's toolchain and command runner, over a moved base.

Kept out of a test file: a `test_commands` method defined there is read as a test the
unit added."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_build_kit.profiles.python_uv import PythonUvProfile


class Profile(PythonUvProfile):
    """The python-uv profile running one lint command and one test command."""

    def lint_command(self, base: str) -> list[str]:
        return ["lint"]

    def test_commands(
        self, repo: Path, changed: list[str], *, root_extras: list[str]
    ) -> list[list[str]]:
        return [["tests"]]


def passing(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, 0, "5 passed\n", "")
