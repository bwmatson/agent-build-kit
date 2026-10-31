"""The ledger of unit-test runs and its rotated copy are ignored in a planning repository
(spec: test-failure-evidence): they are machine-local, and a tracked one would commit the
names of failed tests."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import pytest

from agent_build_kit.pipeline.shell import git
from tests.factories import init_repo


@pytest.mark.parametrize("name", ["runs/test-runs.jsonl", "runs/test-runs.jsonl.1"])
def test_the_scaffolded_ignore_list_ignores_the_ledger_and_its_rotated_copy(
    tmp_path: Path, name: str
) -> None:
    repo = init_repo(tmp_path / "planning")
    template = resources.files("agent_build_kit").joinpath("templates/gitignore").read_text()
    (repo / ".gitignore").write_text(template)

    assert git(repo, "check-ignore", "-q", name, check=False).returncode == 0
