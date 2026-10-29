"""Unit-test stand-ins for a run whose first test command storms and a later one does not.

Kept out of the test module, and the profile hook `test_commands` assigned, not defined: a
scan of a test file for changed test names would take a `def test_commands` for a test.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.pipeline.test_flake_isolation import HookedProfile, Runs


def _with_second_command(
    self: HookedProfile,
    repo: Path,
    changed: list[str],
    *,
    root_extras: list[str],
    **_workers: object,
) -> list[list[str]]:
    first = HookedProfile.test_commands(self, repo, changed, root_extras=root_extras)
    return [*first, ["second"]]


class ThenFailing(HookedProfile):
    """`HookedProfile` with a second test command after the one that storms."""

    # Assigned, not defined: a scan for changed tests takes any `def test_*` for one.
    test_commands = _with_second_command


class AfterTheStorm(Runs):
    """`Runs`, with a second test command that really fails."""

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        if command == ["second"]:
            self.commands.append(command)
            return subprocess.CompletedProcess(command, 1, "an assertion failed\n", "")
        return super().__call__(command, **kwargs)


class ManyFailed(HookedProfile):
    """`HookedProfile` reading 97 failed tests from the output."""

    def failed_tests(self, output: str) -> list[str]:
        return [f"test_one.py::test_case_{number:03}" for number in range(97)]
