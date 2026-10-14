"""A stand-in for `shell.git` that records what it was asked and can fail a command.

A module that runs git through the shared runner holds it as `git`; patching that
name shows the module reached the runner, and the answers it gives back show what
the module does with a failing command.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_build_kit.pipeline import shell


class GitSpy:
    def __init__(self, failing: dict[str, str] | None = None) -> None:
        # git subcommand -> the stderr it fails with
        self.failing = failing or {}
        self.calls: list[tuple[str, ...]] = []

    def __call__(
        self, repo: Path, *args: str, check: bool = True, **kwargs
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        if args[0] in self.failing:
            failed = subprocess.CompletedProcess(
                ["git", *args], 1, stdout="", stderr=self.failing[args[0]]
            )
            if check:
                raise subprocess.CalledProcessError(1, failed.args, "", failed.stderr)
            return failed
        return shell.git(repo, *args, check=check, **kwargs)

    def subcommands(self) -> list[str]:
        return [args[0] for args in self.calls]


def spy_on_git(
    monkeypatch: pytest.MonkeyPatch, module: object, failing: dict[str, str] | None = None
) -> GitSpy:
    """Replace `module.git` with a spy over the real runner."""
    spy = GitSpy(failing)
    monkeypatch.setattr(module, "git", spy)
    return spy
