"""The `acp` adapter refuses a command that writes the planning repo's configuration files,
through the terminal path, with the command policy's reason (spec: review-policy)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.pipeline.command_policy import FENCED_REASON
from agent_build_kit.runtimes import AgentRequest, ToolPolicy
from agent_build_kit.runtimes.acp import AcpRuntime
from tests.factories import git, init_repo
from tests.runtimes.acp_agent import requests, use_agent

BRANCH = "spec/add-marker/1"


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    path = init_repo(tmp_path / "worktree")
    git(path, "checkout", "-q", "-b", BRANCH)
    (path / ".abk" / "out" / "run-1").mkdir(parents=True)
    return path


@pytest.fixture
def planning(tmp_path: Path) -> Path:
    root = tmp_path / "planning"
    root.mkdir()
    (root / "abk.yaml").write_text("repos: {}\n")
    (root / "abk.local.yaml").write_text("runtime: acp\n")
    return root


def run(record: Path, worktree: Path, planning: Path, lines: list[str]) -> list[dict]:
    use_agent(record, act=[{"terminal": line, "args": []} for line in lines])
    AcpRuntime().run(
        AgentRequest(
            prompt="Implement group 1 of add-marker.",
            role="implement",
            cwd=worktree,
            policy=ToolPolicy(fenced_files=(planning / "abk.yaml",)),
        )
    )
    return requests(record, "did/terminal")


@pytest.mark.parametrize("name", ["abk.yaml", "abk.local.yaml"])
def test_a_redirect_or_a_copy_onto_a_configuration_file_is_refused_with_the_policys_reason(
    tmp_path: Path, worktree: Path, planning: Path, name: str
) -> None:
    target = planning / name
    original = target.read_text()

    replies = run(
        tmp_path / "agent.jsonl",
        worktree,
        planning,
        [f"echo x > {target}", f"cp /tmp/m {target}"],
    )

    reason = FENCED_REASON.format(target=target)
    for reply in replies:
        assert "error" in reply or reply.get("exitCode") != 0, reply
        assert reason in json.dumps(reply), reply
    assert target.read_text() == original


def test_a_read_of_a_configuration_file_is_allowed(
    tmp_path: Path, worktree: Path, planning: Path
) -> None:
    [reply] = run(tmp_path / "agent.jsonl", worktree, planning, [f"cat {planning / 'abk.yaml'}"])

    assert "error" not in reply, reply
    assert reply["output"] == "repos: {}\n"
