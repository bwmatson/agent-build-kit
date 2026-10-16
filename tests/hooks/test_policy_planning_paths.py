"""A unit worktree of the planning repo cannot write the planning paths: the pipeline owns the
specs, the state, the two generated pages and the top-level configuration, and a unit's agent
reports `BLOCKED` where one needs changing. Every other path stays writable."""

import subprocess
from pathlib import Path

import pytest

from agent_build_kit.hooks.policy import decide, hook_settings

PLANNING_PATHS = ("openspec", "runs", "docs/unit_graph.md", "docs/unit_cost.md", "abk.yaml")


def checkout(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    return path


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    return checkout(tmp_path.resolve() / "unit-worktree")


def write(target: str | Path, *, cwd: Path) -> dict:
    return {"tool_name": "Write", "cwd": str(cwd), "tool_input": {"file_path": str(target)}}


def reason_of(answer: dict | None) -> str:
    assert answer is not None
    assert answer["hookSpecificOutput"]["permissionDecision"] == "deny"
    return answer["hookSpecificOutput"]["permissionDecisionReason"]


def fenced(payload: dict, **kwargs) -> dict | None:
    return decide(payload, planning_paths=PLANNING_PATHS, **kwargs)


def command_of(settings: dict) -> str:
    return settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]


@pytest.mark.parametrize(
    "relative",
    [
        "openspec/changes/x/tasks.md",
        "runs/units.json",
        "docs/unit_graph.md",
        "docs/unit_cost.md",
        "abk.yaml",
    ],
)
def test_a_planning_path_in_the_unit_worktree_is_denied_with_the_blocked_message(
    worktree: Path, relative: str
) -> None:
    reason = reason_of(fenced(write(worktree / relative, cwd=worktree)))

    assert "BLOCKED: <what and where>" in reason
    assert "pipeline" in reason


@pytest.mark.parametrize(
    "relative", ["src/module.py", "tests/fixtures/x/abk.yaml", "docs/other.md"]
)
def test_every_other_path_in_the_worktree_stays_writable(worktree: Path, relative: str) -> None:
    assert fenced(write(worktree / relative, cwd=worktree)) is None


def test_a_relative_file_path_is_resolved_against_the_run_s_directory(worktree: Path) -> None:
    (worktree / "src").mkdir()

    assert "BLOCKED" in reason_of(fenced(write("abk.yaml", cwd=worktree)))
    assert "BLOCKED" in reason_of(fenced(write("../abk.yaml", cwd=worktree / "src")))
    assert "BLOCKED" in reason_of(fenced(write("../runs/units.json", cwd=worktree / "src")))
    assert fenced(write("module.py", cwd=worktree / "src")) is None
    assert fenced(write("../tests/fixtures/x/abk.yaml", cwd=worktree / "src")) is None


def test_a_path_reached_through_dot_dot_is_the_path_it_resolves_to(worktree: Path) -> None:
    (worktree / "src").mkdir()

    sneaky = worktree / "src" / ".." / "openspec" / "changes" / "x" / "tasks.md"
    harmless = worktree / "openspec" / ".." / "src" / "module.py"

    assert "BLOCKED" in reason_of(fenced(write(sneaky, cwd=worktree)))
    assert fenced(write(harmless, cwd=worktree)) is None


def test_a_directory_that_only_starts_with_a_planning_name_is_not_one(worktree: Path) -> None:
    for relative in ("openspec-notes/x.md", "runs-archive/x.json", "abk.yaml.bak"):
        assert fenced(write(worktree / relative, cwd=worktree)) is None, relative


def test_no_planning_paths_means_the_worktree_is_all_writable(worktree: Path) -> None:
    """A unit of another repo: `openspec/x.md` is an ordinary file there."""
    assert decide(write(worktree / "openspec" / "x.md", cwd=worktree), planning_paths=()) is None
    assert decide(write(worktree / "abk.yaml", cwd=worktree), planning_paths=()) is None


def test_the_specs_message_is_kept_for_the_specs_directory(tmp_path: Path, worktree: Path) -> None:
    specs = tmp_path / "planning" / "openspec"

    reason = reason_of(
        fenced(write(specs / "changes" / "x" / "tasks.md", cwd=worktree), specs=specs)
    )

    assert "read-only for build agents" in reason
    assert "BLOCKED: <what and where>" not in reason


def test_the_planning_repo_message_is_kept_for_a_path_in_it(tmp_path: Path, worktree: Path) -> None:
    planning = checkout(tmp_path / "planning")

    reason = reason_of(
        fenced(write(planning / "docs" / "x.md", cwd=worktree), planning_repo=planning)
    )

    assert "is in the planning repo" in reason


def test_the_outside_worktree_message_is_kept_for_another_checkout(
    tmp_path: Path, worktree: Path
) -> None:
    third = checkout(tmp_path / "third")

    reason = reason_of(fenced(write(third / "x.py", cwd=worktree)))

    assert "outside this unit's worktree" in reason


def test_the_hook_is_told_the_planning_paths() -> None:
    command = command_of(hook_settings(None, planning_paths=PLANNING_PATHS))

    assert "--planning-paths openspec,runs,docs/unit_graph.md,docs/unit_cost.md,abk.yaml" in command


def test_no_planning_paths_means_no_flag() -> None:
    assert "--planning-paths" not in command_of(hook_settings(None, planning_paths=()))
