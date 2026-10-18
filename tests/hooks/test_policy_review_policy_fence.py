"""No agent can change the review policy: the planning repo's abk.yaml is refused to a build
agent and to a track's run by every route a write can take (spec: review-policy)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_build_kit.hooks.policy import decide
from agent_build_kit.pipeline.scratch import scratch_folder


def checkout(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "spec/change/1"], cwd=path, check=True)
    return path


def bash(command: str, *, cwd: Path) -> dict:
    return {"tool_name": "Bash", "cwd": str(cwd), "tool_input": {"command": command}}


def write(target: Path, *, cwd: Path) -> dict:
    return {"tool_name": "Write", "cwd": str(cwd), "tool_input": {"file_path": str(target)}}


def assert_denied(answer: dict | None, route: str) -> None:
    assert answer is not None, route
    assert answer["hookSpecificOutput"]["permissionDecision"] == "deny", route


@pytest.fixture
def planning(tmp_path: Path) -> Path:
    return checkout(tmp_path.resolve() / "planning")


@pytest.fixture
def code_worktree(tmp_path: Path) -> Path:
    worktree = checkout(tmp_path.resolve() / "unit-worktree")
    scratch_folder(worktree).mkdir(parents=True)
    return worktree


def test_a_build_agent_is_refused_a_write_to_abk_yaml_by_every_route(
    planning: Path, code_worktree: Path
) -> None:
    policy = planning / "abk.yaml"
    routes = {
        "file write": write(policy, cwd=code_worktree),
        "shell redirect": bash(f"echo 'review: {{enabled: true}}' > {policy}", cwd=code_worktree),
        "append redirect": bash(f"echo 'review:' >> {policy}", cwd=code_worktree),
        "tee": bash(f"echo x | tee {policy}", cwd=code_worktree),
        "editor command": bash(f"sed -i 's/false/true/' {policy}", cwd=code_worktree),
        "copy over": bash(f"cp /tmp/mine.yaml {policy}", cwd=code_worktree),
        "move over": bash(f"mv /tmp/mine.yaml {policy}", cwd=code_worktree),
    }

    for route, payload in routes.items():
        assert_denied(decide(payload, planning_repo=planning), route)


def test_a_build_agent_in_the_planning_repos_own_worktree_is_refused_by_every_route(
    tmp_path: Path,
) -> None:
    worktree = checkout(tmp_path.resolve() / "planning-unit")
    scratch_folder(worktree).mkdir(parents=True)
    fenced = ("openspec", "runs", "abk.yaml")
    routes = {
        "file write": write(worktree / "abk.yaml", cwd=worktree),
        "editor command": bash("sed -i 's/false/true/' abk.yaml", cwd=worktree),
        "tee": bash("echo x | tee abk.yaml", cwd=worktree),
        "move over": bash("mv /tmp/mine.yaml abk.yaml", cwd=worktree),
    }

    for route, payload in routes.items():
        assert_denied(decide(payload, planning_paths=fenced), route)


def test_a_track_run_is_refused_a_write_to_abk_yaml_by_every_route(planning: Path) -> None:
    change = planning / "openspec" / "changes" / "app-track-1"
    state = planning / "runs"
    routes = {
        "file write": write(planning / "abk.yaml", cwd=planning),
        "shell redirect": bash("echo 'review:' > abk.yaml", cwd=planning),
        "tee": bash("echo x | tee abk.yaml", cwd=planning),
        "editor command": bash("sed -i 's/false/true/' abk.yaml", cwd=planning),
        "move over": bash("mv /tmp/mine.yaml abk.yaml", cwd=planning),
    }

    for route, payload in routes.items():
        answer = decide(
            payload,
            planning_repo=planning,
            planning_state_dir=state,
            planning_change_dir=change,
        )
        assert_denied(answer, route)


def test_a_write_inside_the_changes_own_folder_is_still_allowed(planning: Path) -> None:
    change = planning / "openspec" / "changes" / "app-track-1"
    state = planning / "runs"
    fenced_edit = bash("sed -i 's/false/true/' abk.yaml", cwd=planning)
    allowed = [
        write(change / "proposal.md", cwd=planning),
        bash(f"echo '# Proposal' > {change / 'proposal.md'}", cwd=planning),
    ]

    assert_denied(
        decide(fenced_edit, planning_repo=planning, planning_state_dir=state), "the fence is on"
    )
    for payload in allowed:
        answer = decide(
            payload,
            planning_repo=planning,
            planning_state_dir=state,
            planning_change_dir=change,
        )
        assert answer is None, payload
