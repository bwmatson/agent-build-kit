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


# --- a run that works in the planning repo itself ------------------------------------
#
# The propose phase writes a change, so it runs with the planning repo as its
# working directory. Everything inside a run's own checkout is ordinarily the
# run's to write, which for this phase would include the tick's live state —
# so the planning repo is fenced by path instead of by checkout.


def planning_layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A planning repo with a code checkout nested inside it, as a workspace
    with `path: checkouts/app` has — and the change directory a run was granted."""
    planning = tmp_path / "planning"
    code = planning / "checkouts" / "app"
    for checkout in (planning, code):
        checkout.mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)
    return planning, code, planning / "openspec" / "changes" / "app-track-1"


def test_a_propose_run_may_write_its_change_and_its_run_log(tmp_path: Path) -> None:
    planning, _, change = planning_layout(tmp_path)
    state = planning / "runs"

    def answer(target: Path) -> dict | None:
        return decide(
            write_to(target, cwd=planning),
            planning_repo=planning,
            planning_state_dir=state,
            planning_change_dir=change,
        )

    assert answer(change / "proposal.md") is None
    assert answer(change / "specs" / "thing" / "spec.md") is None, "the change is a tree"
    assert answer(state / "20260930-app-propose.md") is None, "its run log"
    assert answer(state / "tracked-issues.md") is None, "and the tracker"


def test_a_propose_run_may_not_write_the_rest_of_the_planning_repo(tmp_path: Path) -> None:
    """The reason the grant is a path and not the checkout: cwd is the planning
    repo, and the tick's live state lives in it."""
    planning, _, change = planning_layout(tmp_path)
    state = planning / "runs"

    def answer(target: Path) -> dict | None:
        return decide(
            write_to(target, cwd=planning),
            planning_repo=planning,
            planning_state_dir=state,
            planning_change_dir=change,
        )

    for refused in (
        state / "units.json",
        state / "paused.json",
        planning / "abk.yaml",
        planning / "docs" / "unit_graph.md",
        planning / "openspec" / "config.yaml",
        planning / "openspec" / "changes" / "someone-elses-change" / "tasks.md",
        planning / "openspec" / "specs" / "thing" / "spec.md",
    ):
        denied = answer(refused)
        assert denied is not None, refused
        assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_a_path_out_of_the_change_does_not_stay_in_it(tmp_path: Path) -> None:
    """`..` is resolved before the decision, so the grant cannot be walked out of."""
    planning, _, change = planning_layout(tmp_path)
    sneaky = change / ".." / ".." / ".." / "runs" / "units.json"

    denied = decide(
        write_to(sneaky, cwd=planning),
        planning_repo=planning,
        planning_state_dir=planning / "runs",
        planning_change_dir=change,
    )

    assert denied is not None


def test_a_checkout_nested_inside_the_planning_repo_is_still_its_own(tmp_path: Path) -> None:
    """Fencing the planning repo by path would fence a code checkout that lives
    under it. The fence applies to what the planning repo's own git owns."""
    planning, code, change = planning_layout(tmp_path)

    allowed = decide(
        write_to(code / "src" / "thing.py", cwd=code),
        planning_repo=planning,
        planning_state_dir=planning / "runs",
    )

    assert allowed is None


def test_a_discovery_run_is_not_granted_a_change(tmp_path: Path) -> None:
    """Only the propose phase is handed `planning_change_dir`. Without it a
    discovery run cannot write a change, which is what keeps health and
    improve read-only with respect to what the pipeline will build."""
    planning, code, change = planning_layout(tmp_path)

    denied = decide(
        write_to(change / "tasks.md", cwd=code),
        planning_repo=planning,
        planning_state_dir=planning / "runs",
    )

    assert denied is not None


def test_init_s_proposal_is_unaffected(tmp_path: Path) -> None:
    """`abk init` writes a change into the planning repo with no `planning_repo`
    given at all; the fence is opt-in and must not reach it."""
    planning, _, change = planning_layout(tmp_path)

    assert decide(write_to(change / "tasks.md", cwd=planning)) is None
    assert decide(write_to(planning / "abk.yaml", cwd=planning)) is None


def test_the_hook_is_told_which_change_it_may_write() -> None:
    from agent_build_kit.hooks.policy import hook_settings

    settings = hook_settings(
        None,
        planning_repo=Path("/srv/planning"),
        planning_state_dir=Path("/srv/planning/runs"),
        planning_change_dir=Path("/srv/planning/openspec/changes/app-track-1"),
    )

    command = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert "--planning-change-dir /srv/planning/openspec/changes/app-track-1" in command
