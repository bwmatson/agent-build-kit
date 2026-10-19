"""An install a builder makes through `abk install-config` is on the run log on the `acp`
runtime too: the line the command prints is reported when its tool call completes."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from agent_build_kit.pipeline.install_record import install_line
from agent_build_kit.runtimes import AgentRequest, ToolPolicy
from agent_build_kit.runtimes.acp import AcpRuntime
from tests.factories import git, init_repo
from tests.runtimes.acp_agent import use_agent

COMMAND = "abk install-config .abk/proposed/p.yaml pkg/.pre-commit-config.yaml"
TARGET = "pkg/.pre-commit-config.yaml"
STAGED = "repos: []\n"
DIGEST = hashlib.sha256(STAGED.encode()).hexdigest()
LINE = install_line(TARGET, DIGEST, len(STAGED))


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    path = init_repo(tmp_path / "worktree")
    git(path, "checkout", "-q", "-b", "spec/add-marker/1")
    return path


@pytest.fixture
def specs(tmp_path: Path) -> Path:
    path = tmp_path / "planning" / "openspec" / "specs"
    path.mkdir(parents=True)
    return path


def reported(record: Path, worktree: Path, specs: Path, status: str) -> list[str]:
    lines: list[str] = []
    use_agent(record, act=[{"unasked": COMMAND, "status": status, "output": f"{LINE}\n"}])
    AcpRuntime().run(
        AgentRequest(
            prompt="Implement group 1 of add-marker.",
            role="implement",
            cwd=worktree,
            add_dirs=(specs,),
            policy=ToolPolicy(specs_dir=specs),
            on_event=lines.append,
        )
    )
    return lines


def test_a_completed_install_puts_its_target_and_hash_on_the_log_once(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    lines = reported(tmp_path / "agent.jsonl", worktree, specs, "completed")

    assert [text for text in lines if DIGEST in text and TARGET in text] == [f"  {LINE}"]


def test_an_install_that_failed_is_not_on_the_log(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    lines = reported(tmp_path / "agent.jsonl", worktree, specs, "failed")

    assert not [text for text in lines if DIGEST in text]
