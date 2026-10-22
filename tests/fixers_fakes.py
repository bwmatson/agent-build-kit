"""Stand-ins for the fixer pass of a build: a profile that declares a fix command, a command
runner that does git for real and records every other command, and the workspace the pass
reads its repo settings from."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_build_kit import config as config_module
from agent_build_kit.config import WorkspaceConfig

# What a fixer command does to the tree: given the argv, the directory it ran in and the
# number of the call, it edits files and answers an exit status (or raises, as a program that
# is missing does).
Behaviour = Callable[[list[str], Path, int], int]


class FakeProfile:
    """A profile whose fix command is `fmt` over the files."""

    name = "fake"

    def fix_command(self, files: list[str]) -> list[str] | None:
        return ["fmt", *files] if files else None


class Bare:
    """A profile that declares nothing about fixers."""

    name = "bare"


class FakeRun:
    """The command runner `build_fixers` takes: git runs for real, any other command is
    recorded as (argv, directory) and then handed to `behaviour`."""

    def __init__(self, behaviour: Behaviour | None = None) -> None:
        self.calls: list[tuple[list[str], Path]] = []
        self.behaviour = behaviour

    def __call__(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if args[0] == "git":
            return subprocess.run(args, capture_output=True, text=True, check=False, **kwargs)
        where = Path(kwargs["cwd"])
        self.calls.append((list(args), where))
        status = self.behaviour(list(args), where, len(self.calls)) if self.behaviour else 0
        return subprocess.CompletedProcess(args, status, "", "")


def activate_app(**app: Any) -> None:
    """Activate a workspace whose `app` repo has these settings besides its path and slug."""
    config_module.activate(
        WorkspaceConfig.model_validate(
            {
                "repos": {
                    "app": {"path": "/work/app", "slug": "example/app", **app},
                    "platform": {"path": "/work/platform", "slug": "example/platform"},
                }
            }
        ),
        config_module.active_root(),
    )
