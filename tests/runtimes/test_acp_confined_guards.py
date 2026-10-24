"""With a confined policy the ACP client stands its command-text config fence down, because the
terminal runs under the launcher, and keeps every check that is about meaning or that guards the
kit's own unsandboxed process (spec: sandbox-guard-fallback).

Unconfined, the fence refuses as `test_acp_fenced_config.py` shows. Each test that pins a guard
which stays in both modes also pins the stand-down in the same run, so the file as a whole is
about what `confined` changes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.config import dump
from agent_build_kit.pipeline.command_policy import FENCED_REASON, check_command, check_no_push
from agent_build_kit.runtimes import AgentRequest, ToolPolicy
from agent_build_kit.runtimes.acp import AcpRuntime
from tests.conftest import make_installation
from tests.factories import git, init_repo
from tests.runtimes.acp_agent import requests, use_agent
from tests.runtimes.acp_sandbox_support import Recording, Scene

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
    return root


def fence_probe(planning: Path) -> dict[str, Any]:
    """A terminal write onto the planning repo's configuration file, outside the worktree."""
    return {"terminal": "sh", "args": ["-c", f"echo x > {planning / 'abk.yaml'}"]}


def run(record: Path, worktree: Path, policy: ToolPolicy, act: list[dict[str, Any]]) -> None:
    use_agent(record, act=act)
    AcpRuntime().run(
        AgentRequest(prompt="Implement group 1.", role="implement", cwd=worktree, policy=policy)
    )


def assert_fence_stood_down(reply: dict[str, Any], planning: Path) -> None:
    assert FENCED_REASON.format(target=planning / "abk.yaml") not in json.dumps(reply), reply
    assert "error" not in reply and reply.get("exitCode") == 0, reply


def test_a_confined_terminal_may_write_the_planning_repos_config_by_text(
    tmp_path: Path, worktree: Path, planning: Path
) -> None:
    """The kernel refuses what the launcher does not grant; the text rule would only repeat it."""
    record = tmp_path / "agent.jsonl"

    run(
        record,
        worktree,
        ToolPolicy(confined=True, fenced_files=(planning / "abk.yaml",)),
        [fence_probe(planning)],
    )

    [reply] = requests(record, "did/terminal")
    assert_fence_stood_down(reply, planning)
    assert (planning / "abk.yaml").read_text() == "x\n"


def test_a_confined_fenced_file_inside_the_checkout_is_still_fenced_by_text(
    tmp_path: Path, worktree: Path, planning: Path
) -> None:
    """`planning_paths` name files in the worktree, which the launcher grants whole."""
    record = tmp_path / "agent.jsonl"
    inside = worktree / "abk.yaml"
    inside.write_text("repos: {}\n")

    run(
        record,
        worktree,
        ToolPolicy(
            confined=True, planning_paths=("abk.yaml",), fenced_files=(planning / "abk.yaml",)
        ),
        [fence_probe(planning), {"terminal": "sh", "args": ["-c", f"echo x > {inside}"]}],
    )

    stood_down, refused = requests(record, "did/terminal")
    assert_fence_stood_down(stood_down, planning)
    assert FENCED_REASON.format(target=inside) in json.dumps(refused), refused
    assert inside.read_text() == "repos: {}\n"


def test_the_kits_own_process_writes_for_the_agent_so_the_client_refuses_outside_the_worktree_when_confined(
    tmp_path: Path, worktree: Path, planning: Path
) -> None:
    """`write_text_file` is performed by abk itself, which the launcher does not wrap."""
    record = tmp_path / "agent.jsonl"
    outside = tmp_path / "elsewhere.txt"

    run(
        record,
        worktree,
        ToolPolicy(confined=True, fenced_files=(planning / "abk.yaml",)),
        [fence_probe(planning), {"write": str(outside), "content": "x\n"}],
    )

    [reply] = requests(record, "did/terminal")
    assert_fence_stood_down(reply, planning)
    [written] = requests(record, "did/write")
    assert "error" in written, written
    assert not outside.exists()


@pytest.mark.parametrize("kind", ["edit", "delete", "move"])
def test_the_kits_own_process_performs_approved_edits_so_the_verdict_refuses_outside_the_worktree_when_confined(
    tmp_path: Path, worktree: Path, planning: Path, kind: str
) -> None:
    record = tmp_path / "agent.jsonl"

    run(
        record,
        worktree,
        ToolPolicy(confined=True, fenced_files=(planning / "abk.yaml",)),
        [fence_probe(planning), {"ask": kind, "paths": [str(tmp_path / "elsewhere.txt")]}],
    )

    [reply] = requests(record, "did/terminal")
    assert_fence_stood_down(reply, planning)
    [answer] = requests(record, "did/ask")
    assert answer["optionKind"] != "allow_once", answer


@pytest.mark.parametrize(
    "line",
    [
        pytest.param("gh pr merge 4", id="merge"),
        pytest.param(f"git push origin {BRANCH}", id="push"),
        pytest.param("git push --force origin main", id="force-push"),
        pytest.param("git commit --no-verify -m x", id="no-verify"),
    ],
)
def test_the_meaning_rules_apply_to_a_confined_terminal(
    tmp_path: Path, worktree: Path, planning: Path, line: str
) -> None:
    record = tmp_path / "agent.jsonl"
    reason = check_command(line, branch=BRANCH).reason or check_no_push(line).reason
    assert reason, f"{line!r} is meant to be one the rules forbid"

    run(
        record,
        worktree,
        ToolPolicy(confined=True, fenced_files=(planning / "abk.yaml",)),
        [fence_probe(planning), {"terminal": "sh", "args": ["-c", line]}],
    )

    stood_down, refused = requests(record, "did/terminal")
    assert_fence_stood_down(stood_down, planning)
    assert "error" in refused or refused.get("exitCode") != 0, refused
    assert reason in json.dumps(refused, ensure_ascii=False), refused


def test_a_confined_run_that_may_not_commit_refuses_a_commit(
    tmp_path: Path, worktree: Path, planning: Path
) -> None:
    record = tmp_path / "agent.jsonl"

    run(
        record,
        worktree,
        ToolPolicy(confined=True, no_commit=True, fenced_files=(planning / "abk.yaml",)),
        [fence_probe(planning), {"terminal": "git", "args": ["commit", "-q", "-m", "x"]}],
    )

    stood_down, refused = requests(record, "did/terminal")
    assert_fence_stood_down(stood_down, planning)
    assert "error" in refused or refused.get("exitCode") != 0, refused


def test_install_config_still_works_as_a_child_of_a_confined_agent(
    acp_scene: Scene, backend: Recording, tmp_path: Path
) -> None:
    """`abk install-config` writes inside the worktree, which the launcher grants, so it needs
    no exception; the config file outside is out of reach by the kernel, not by the text rule."""
    installation = make_installation(tmp_path / "installation")
    config = acp_scene.record_dir / "abk.yaml"
    config.write_text(dump(installation.config))
    git(acp_scene.worktree, "init", "-q")
    staged = acp_scene.worktree / ".abk" / "proposed" / "p.yaml"
    staged.parent.mkdir(parents=True)
    staged.write_text("repos: []\n")
    acp_scene.act(
        {"terminal": "sh", "args": ["-c", f"echo x > {acp_scene.target}"]},
        {
            "terminal": sys.executable,
            "args": [
                "-m",
                "agent_build_kit",
                "--config",
                str(config),
                "install-config",
                ".abk/proposed/p.yaml",
                ".pre-commit-config.yaml",
            ],
        },
    )

    AcpRuntime().run(
        AgentRequest(
            prompt="Go.",
            role="implement",
            cwd=acp_scene.worktree,
            policy=ToolPolicy(
                sandbox=acp_scene.policy(), confined=True, fenced_files=(acp_scene.target,)
            ),
        )
    )

    protected, installed = requests(acp_scene.record, "did/terminal")
    assert FENCED_REASON.format(target=acp_scene.target) not in json.dumps(protected), protected
    assert "denied" in protected["output"].lower(), protected
    assert acp_scene.target.read_text() == "original\n"
    assert installed["exitCode"] == 0, installed
    assert (acp_scene.worktree / ".pre-commit-config.yaml").read_text() == "repos: []\n"
