"""A unit that changes a node test file has that file run again under load after unit-test
passes (spec: node-npm-lint-and-test). The command runner is the faked boundary."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import cast

from agent_build_kit import profiles
from agent_build_kit.pipeline.wiring import build_unit_test
from agent_build_kit.profiles.base import ToolchainProfile
from tests.conftest import make_installation
from tests.factories import git, init_repo
from tests.node_workspace import manifest, touch

TEST = "src/a.test.ts"


class Runs:
    """Answers every command with a pass and keeps them."""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        self.commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")


def test_a_changed_node_test_file_is_run_again_by_its_path(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    manifest(repo, "solo")
    touch(repo, TEST)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    base = git(repo, "rev-parse", "HEAD").strip()
    (repo / TEST).write_text("// changed\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "unit")
    make_installation(tmp_path / "planning", limits={"unit_test_repeat_runs": 2})
    runs = Runs()

    passed, _ = build_unit_test(
        profile=cast(ToolchainProfile, profiles.get("node-npm")),
        run=runs,
        changed=lambda *a: [TEST],
    )(cwd=repo, base=base)

    assert passed
    repeats = [c for c in runs.commands if c[5:] == [TEST]]
    assert len(repeats) == 2
