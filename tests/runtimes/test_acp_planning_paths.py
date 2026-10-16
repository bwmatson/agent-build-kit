"""The ACP client fences the planning paths as the Claude Code hook does: a unit of the planning
repo's repository cannot write the specs, the state, the generated pages or `abk.yaml` in its
worktree, through a file write or an edit permission request, and writes anything else."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.runtimes import AgentRequest, ToolPolicy
from agent_build_kit.runtimes.acp import AcpRuntime
from tests.factories import git, init_repo
from tests.runtimes.acp_agent import requests, use_agent

FENCED = ("openspec", "runs", "abk.yaml")
REFUSED = ["abk.yaml", "openspec/changes/x/tasks.md", "runs/units.json"]
ALLOWED = ["src/module.py", "tests/fixtures/x/abk.yaml"]


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    path = init_repo(tmp_path / "worktree")
    git(path, "checkout", "-q", "-b", "spec/add-marker/1")
    return path


def run(record: Path, worktree: Path, paths: tuple[str, ...], **agent: Any) -> None:
    use_agent(record, **agent)
    AcpRuntime().run(
        AgentRequest(
            prompt="Change it.",
            role="implement",
            cwd=worktree,
            policy=ToolPolicy(planning_paths=paths),
        )
    )


@pytest.mark.parametrize("relative", REFUSED)
def test_a_write_to_a_planning_path_is_refused_and_says_who_owns_it(
    tmp_path: Path, worktree: Path, relative: str
) -> None:
    record = tmp_path / "agent.jsonl"

    run(record, worktree, FENCED, act=[{"write": str(worktree / relative), "content": "x\n"}])

    [answer] = requests(record, "did/write")
    assert "BLOCKED: <what and where>" in str(answer["error"])
    assert not (worktree / relative).exists()


@pytest.mark.parametrize("relative", ALLOWED)
def test_a_write_elsewhere_in_the_worktree_is_performed(
    tmp_path: Path, worktree: Path, relative: str
) -> None:
    record = tmp_path / "agent.jsonl"

    run(record, worktree, FENCED, act=[{"write": str(worktree / relative), "content": "x\n"}])

    [answer] = requests(record, "did/write")
    assert "error" not in answer, answer
    assert (worktree / relative).read_text() == "x\n"


@pytest.mark.parametrize("relative", REFUSED)
def test_an_edit_of_a_planning_path_is_refused(
    tmp_path: Path, worktree: Path, relative: str
) -> None:
    record = tmp_path / "agent.jsonl"

    run(record, worktree, FENCED, act=[{"ask": "edit", "paths": [str(worktree / relative)]}])

    [answer] = requests(record, "did/ask")
    assert answer["optionKind"] != "allow_once", answer


@pytest.mark.parametrize("relative", ALLOWED)
def test_an_edit_elsewhere_in_the_worktree_is_allowed(
    tmp_path: Path, worktree: Path, relative: str
) -> None:
    record = tmp_path / "agent.jsonl"

    run(record, worktree, FENCED, act=[{"ask": "edit", "paths": [str(worktree / relative)]}])

    [answer] = requests(record, "did/ask")
    assert answer["optionKind"] == "allow_once", answer


def test_with_no_planning_paths_the_specs_path_is_writable(tmp_path: Path, worktree: Path) -> None:
    record = tmp_path / "agent.jsonl"
    target = worktree / "openspec" / "x.md"

    run(record, worktree, (), act=[{"write": str(target), "content": "x\n"}])

    [answer] = requests(record, "did/write")
    assert "error" not in answer, answer
    assert target.read_text() == "x\n"
