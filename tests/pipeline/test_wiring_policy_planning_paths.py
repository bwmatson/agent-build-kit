"""A unit whose repo shares the planning root's repository carries the planning paths in its tool
policy and in the hook it runs under; a unit of another repo carries none."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit import runtimes
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.wiring import build_runner
from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.claude_code import build_argv
from tests.factories import init_repo, unit
from tests.planning_worktree_support import in_repo, installation_at
from tests.runner_fakes import approving
from tests.runtimes.stand_in import StandInRuntime


def build_request(
    root: Path, repo_path: Path, monkeypatch: pytest.MonkeyPatch, cwd: Path
) -> tuple[AgentRequest, tuple[str, ...]]:
    """The request the build run for a unit of `app` asks its runtime for, and the installation's
    planning paths."""
    installation = installation_at(root, repo_path)
    runtime = StandInRuntime(answer=approving())
    monkeypatch.setattr(runtimes, "active", lambda: runtime)
    runner = build_runner(
        unit("feature/1", change="feature", repo="app"),
        store=UnitStore(root / "units.json"),
        installation=installation,
        log=lambda _: None,
    )
    runner.run("Implement it.", cwd=cwd, model="m")
    return runtime.request, installation.planning_paths


def hook_command(request: AgentRequest) -> str:
    argv = build_argv(request)
    settings = json.loads(argv[argv.index("--settings") + 1])
    return settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]


def test_a_unit_of_the_planning_repo_gets_the_planning_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = in_repo(tmp_path)
    cwd = tmp_path / "tree"
    cwd.mkdir()

    request, paths = build_request(setup.worktree, setup.working_copy, monkeypatch, cwd)

    assert paths
    assert request.policy is not None
    assert request.policy.planning_paths == paths
    assert "--planning-paths " + ",".join(paths) in hook_command(request)


def test_a_unit_of_another_repo_gets_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    planning = init_repo(tmp_path / "planning")
    other = init_repo(tmp_path / "other")
    cwd = tmp_path / "tree"
    cwd.mkdir()

    request, paths = build_request(planning, other, monkeypatch, cwd)

    assert paths
    assert request.policy is not None
    assert request.policy.planning_paths == ()
    assert "--planning-paths" not in hook_command(request)
