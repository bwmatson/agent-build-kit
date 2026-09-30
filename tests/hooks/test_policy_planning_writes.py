"""A track run writes its run log and tracker in the planning repo, from a
code repo's checkout: the hook lets exactly that through, and a path restore
in the planning repo is not a branch change."""

import subprocess
from pathlib import Path

from agent_build_kit.hooks.policy import decide
from agent_build_kit.pipeline.command_policy import check_command

PLANNING = "/srv/planning"


def write_to(target: Path, *, cwd: Path) -> dict:
    return {"tool_name": "Write", "cwd": str(cwd), "tool_input": {"file_path": str(target)}}


def test_a_path_restore_in_the_planning_repo_is_allowed() -> None:
    for command in (
        f"git -C {PLANNING} checkout -- runs/x.md",
        f"cd {PLANNING} && git checkout HEAD -- runs/x.md",
    ):
        verdict = check_command(command, branch="main", planning_repo=Path(PLANNING))

        assert verdict.allowed, command


def test_a_track_run_may_write_under_the_planning_state_directory(tmp_path: Path) -> None:
    code, planning, third = (tmp_path / name for name in ("code", "planning", "third"))
    for checkout in (code, planning, third):
        checkout.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)
    state = planning / "runs"

    def answer(target: Path) -> dict | None:
        return decide(write_to(target, cwd=code), planning_repo=planning, planning_state_dir=state)

    assert answer(state / "x.md") is None
    assert answer(state / "tracked-issues.md") is None
    assert answer(code / "src.py") is None
    for refused in (
        third / "x.md",
        state / "units.json",
        state / "paused.json",
        planning / "docs" / "x.md",
    ):
        denied = answer(refused)
        assert denied is not None, refused
        assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert decide(write_to(state / "x.md", cwd=code)) is not None, "no state directory, no way in"
