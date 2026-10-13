"""Stand-ins for the tier 1 runner's toolchain and command runner, over a moved base.

The profile's `test_commands` is bound by assignment: a function named `test_*` defined in
a file under `tests/` is read as a test the unit added."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_build_kit.profiles.python_uv import PythonUvProfile


def one_test_command(
    self: PythonUvProfile, repo: Path, changed: list[str], *, root_extras: list[str]
) -> list[list[str]]:
    return [["tests"]]


class Profile(PythonUvProfile):
    """The python-uv profile running one lint command and one test command."""

    def lint_command(self, base: str) -> list[str]:
        return ["lint"]

    test_commands = one_test_command


def passing(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, 0, "5 passed\n", "")
