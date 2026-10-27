"""The tracking copy under `<state dir>/changes/` is the pipeline's, though a track may write
Markdown elsewhere in the state directory."""

import subprocess
from pathlib import Path

from agent_build_kit.hooks.policy import decide


def write_to(target: Path, *, cwd: Path) -> dict:
    return {"tool_name": "Write", "cwd": str(cwd), "tool_input": {"file_path": str(target)}}


def denied(answer: dict | None) -> bool:
    return answer is not None and answer["hookSpecificOutput"]["permissionDecision"] == "deny"


def layout(tmp_path: Path) -> tuple[Path, Path]:
    """A code checkout, and a state directory beside it."""
    code, state = tmp_path / "code", tmp_path / "state"
    code.mkdir()
    state.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=code, check=True)
    return code, state


def test_a_build_agent_writing_the_copy_is_denied_as_before(tmp_path: Path) -> None:
    code, state = layout(tmp_path)

    for name in ("tasks.md", "follow-ups.md"):
        target = state / "changes" / "add-marker" / name
        assert denied(decide(write_to(target, cwd=code))), name
        assert denied(decide(write_to(target, cwd=code), planning_reports_dir=state)), (
            f"{name}: a track run's grant of the state directory's Markdown stops short of it"
        )


def test_a_track_runs_grant_allows_a_run_log_and_denies_anything_under_changes(
    tmp_path: Path,
) -> None:
    code, state = layout(tmp_path)

    def answer(target: Path) -> dict | None:
        return decide(write_to(target, cwd=code), planning_reports_dir=state)

    assert answer(state / "run-log.md") is None
    assert answer(state / "tracked-issues.md") is None
    assert answer(state / "reports" / "health.md") is None
    assert denied(answer(state / "changes" / "add-marker" / "tasks.md"))
    assert denied(answer(state / "changes" / "add-marker" / "notes.md"))
    assert denied(answer(state / "changes" / "other-change" / "follow-ups.md"))
    assert denied(answer(state / "units.json"))
