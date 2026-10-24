"""When the step is confined by the kernel, the hook stands down its location guards (the worktree
check on the file tools and the specs fence) and keeps every guard about meaning (spec:
sandbox-guard-fallback). Without `--confined` each applies exactly as before."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from agent_build_kit.hooks.policy import decide, hook_settings

PLANNING_PATHS = ("openspec", "abk.yaml")
FILE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def checkout(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "spec/change/1"], cwd=path, check=True)
    return path


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    return checkout(tmp_path.resolve() / "unit-worktree")


@pytest.fixture
def elsewhere(tmp_path: Path) -> Path:
    return checkout(tmp_path.resolve() / "other-checkout")


def file_call(tool: str, target: Path, cwd: Path) -> dict:
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    return {"tool_name": tool, "cwd": str(cwd), "tool_input": {key: str(target)}}


def bash(command: str, cwd: Path) -> dict:
    return {"tool_name": "Bash", "cwd": str(cwd), "tool_input": {"command": command}}


def command_of(settings: dict) -> str:
    return settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]


def denied(answer: dict | None) -> bool:
    return answer is not None and answer["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.parametrize("tool", FILE_TOOLS)
def test_a_write_outside_the_worktree_is_left_to_the_sandbox_when_confined(
    tool: str, worktree: Path, elsewhere: Path
) -> None:
    call = file_call(tool, elsewhere / "NOTES.md", worktree)

    assert denied(decide(call))
    assert denied(decide(call, confined=False))
    assert decide(call, confined=True) is None


def stands_down(worktree: Path, elsewhere: Path) -> bool:
    """Whether a confined hook leaves a write outside the worktree to the sandbox."""
    return decide(file_call("Write", elsewhere / "NOTES.md", worktree), confined=True) is None


@pytest.mark.parametrize("tool", FILE_TOOLS)
def test_the_specs_fence_stands_down_when_confined(
    tool: str, worktree: Path, tmp_path: Path
) -> None:
    specs = tmp_path.resolve() / "planning" / "openspec"
    call = file_call(tool, specs / "changes" / "c" / "tasks.md", worktree)

    assert denied(decide(call, specs=specs))
    assert decide(call, specs=specs, confined=True) is None


@pytest.mark.parametrize("tool", FILE_TOOLS)
def test_a_planning_path_in_the_worktree_is_refused_in_both_modes(
    tool: str, worktree: Path, elsewhere: Path
) -> None:
    call = file_call(tool, worktree / "abk.yaml", worktree)

    assert stands_down(worktree, elsewhere)
    assert denied(decide(call, planning_paths=PLANNING_PATHS))
    assert denied(decide(call, planning_paths=PLANNING_PATHS, confined=True))


@pytest.mark.parametrize("confined", [False, True])
@pytest.mark.parametrize(
    "command",
    [
        "gh pr merge 4",
        "git push origin main",
        "git push --force origin spec/change/1",
        "git commit --no-verify -m x",
    ],
)
def test_the_meaning_guards_apply_in_both_modes(
    command: str, confined: bool, worktree: Path, elsewhere: Path
) -> None:
    assert stands_down(worktree, elsewhere)
    assert denied(decide(bash(command, worktree), confined=confined))


@pytest.mark.parametrize("confined", [False, True])
def test_a_commit_is_refused_when_the_run_may_not_commit_in_both_modes(
    confined: bool, worktree: Path, elsewhere: Path
) -> None:
    assert stands_down(worktree, elsewhere)
    assert denied(decide(bash('git commit -m "x"', worktree), no_commit=True, confined=confined))


def test_the_hook_process_stands_down_when_given_the_flag(worktree: Path, elsewhere: Path) -> None:
    call = json.dumps(file_call("Write", elsewhere / "NOTES.md", worktree))

    def run(*flags: str) -> str:
        return subprocess.run(
            [sys.executable, "-m", "agent_build_kit.hooks.policy", *flags],
            input=call,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    assert '"deny"' in run()
    assert run("--confined") == ""


def test_the_hook_process_still_refuses_a_merge_given_the_flag(worktree: Path) -> None:
    run = subprocess.run(
        [sys.executable, "-m", "agent_build_kit.hooks.policy", "--confined"],
        input=json.dumps(bash("gh pr merge 4", worktree)),
        capture_output=True,
        text=True,
        check=True,
    )

    assert '"deny"' in run.stdout
    assert "merge" in run.stdout


def test_the_hook_is_registered_with_the_flag_only_when_confined() -> None:
    assert "--confined" not in command_of(hook_settings(Path("/repo")))
    assert " --confined" in command_of(hook_settings(Path("/repo"), confined=True))


def test_a_write_with_no_worktree_to_place_it_in_is_still_refused_when_confined(
    tmp_path: Path,
) -> None:
    plain = tmp_path.resolve() / "plain"
    plain.mkdir()
    call = file_call("Write", plain / "x", plain)

    assert denied(decide(call))
    assert denied(decide(call, confined=True))
