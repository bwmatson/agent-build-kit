"""A build run's hook is told the planning repo's abk.yaml, so the shell routes the command
policy names cannot write the review policy from a unit's worktree (spec: review-policy). The
test drives the real path: the request `build_runner` asks its runtime for, the hook command
`build_argv` makes of it, and `policy.main` run with that command's arguments and a payload on
stdin."""

from __future__ import annotations

import io
import json
import shlex
import subprocess
from pathlib import Path

import pytest

from agent_build_kit.hooks import policy
from agent_build_kit.pipeline.scratch import scratch_folder
from tests.factories import init_repo
from tests.pipeline.test_wiring_policy_planning_paths import build_request, hook_command
from tests.planning_worktree_support import in_repo


def hook_argv(command: str) -> list[str]:
    words = shlex.split(command)
    return words[words.index("agent_build_kit.hooks.policy") + 1 :]


def answer(
    argv: list[str], payload: dict, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> str | None:
    """The hook's decision (`deny` or None) for `payload`, from a real `main` run."""
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    assert policy.main(argv) == 0
    out = capsys.readouterr().out
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out.strip() else None


def routes(config: Path) -> dict[str, str]:
    return {
        "redirect": f"echo x > {config}",
        "tee": f"echo x | tee {config}",
        "sed -i": f"sed -i 's/a/b/' {config}",
        "cp": f"cp /tmp/mine.yaml {config}",
        "mv": f"mv /tmp/mine.yaml {config}",
        "cp into the directory": f"cp /tmp/abk.yaml {config.parent}/",
        "dd": f"dd if=/tmp/mine.yaml of={config}",
        "perl -pi": f"perl -pi -e 's/a/b/' {config}",
        "after a cd": f"cd {config.parent} && sed -i 's/a/b/' abk.yaml",
        "through a variable": f'P={config}; tee "$P" < /tmp/mine.yaml',
    }


def worktree_with_scratch(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "spec/change/1"], cwd=path, check=True)
    scratch_folder(path).mkdir(parents=True)
    return path


def test_a_build_runs_hook_denies_every_shell_route_onto_the_planning_abk_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    planning = init_repo(tmp_path / "planning")
    other = init_repo(tmp_path / "other")
    cwd = tmp_path / "tree"
    cwd.mkdir()
    request, _ = build_request(planning, other, monkeypatch, cwd)
    argv = hook_argv(hook_command(request))
    worktree = worktree_with_scratch(tmp_path / "unit-worktree")

    assert "--planning-repo" not in argv, "a build is not a track"
    for route, command in routes(planning.resolve() / "abk.yaml").items():
        payload = {"tool_name": "Bash", "cwd": str(worktree), "tool_input": {"command": command}}
        assert answer(argv, payload, monkeypatch, capsys) == "deny", route


def test_a_read_of_the_planning_abk_yaml_and_a_write_elsewhere_are_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    planning = init_repo(tmp_path / "planning")
    other = init_repo(tmp_path / "other")
    cwd = tmp_path / "tree"
    cwd.mkdir()
    request, _ = build_request(planning, other, monkeypatch, cwd)
    argv = hook_argv(hook_command(request))
    worktree = worktree_with_scratch(tmp_path / "unit-worktree")
    config = planning.resolve() / "abk.yaml"
    assert request.policy is not None
    assert request.policy.fenced_files == (config,)

    for command in (f"cat {config}", f"sed -n --silent 1p {config}", "cp /tmp/a /tmp/b"):
        payload = {"tool_name": "Bash", "cwd": str(worktree), "tool_input": {"command": command}}
        assert answer(argv, payload, monkeypatch, capsys) is None, command


def test_a_unit_of_the_planning_repos_own_repository_cannot_write_the_live_abk_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    setup = in_repo(tmp_path)
    cwd = tmp_path / "tree"
    cwd.mkdir()
    request, _ = build_request(setup.worktree, setup.working_copy, monkeypatch, cwd)
    argv = hook_argv(hook_command(request))
    worktree = worktree_with_scratch(tmp_path / "unit-worktree")

    for route, command in routes(setup.worktree.resolve() / "abk.yaml").items():
        payload = {"tool_name": "Bash", "cwd": str(worktree), "tool_input": {"command": command}}
        assert answer(argv, payload, monkeypatch, capsys) == "deny", route
