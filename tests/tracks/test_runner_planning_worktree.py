"""A track phase's bookkeeping is committed on the pipeline worktree's detached HEAD and pushed
as `HEAD:<default>`, however the phase's agent leaves HEAD.

Against real git: the person's working copy (on a feature branch, so the default branch is free
to be checked out, as the old behaviour would), the pipeline worktree, a bare origin, and a second
clone standing in for anyone else pushing."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.shell import git as run_git
from agent_build_kit.tracks import runner
from tests.factories import commit, git
from tests.planning_worktree_support import InRepo, in_repo, installation_at, publish_elsewhere
from tests.tracks.test_runner_planning_repo import doing, log_name, phase


def pipeline(tmp_path: Path) -> tuple[InRepo, Installation]:
    setup = in_repo(tmp_path)
    git(setup.working_copy, "checkout", "-q", "-b", "feature")
    return setup, installation_at(setup.worktree, setup.working_copy)


def origin_main(setup: InRepo) -> str:
    assert setup.origin is not None
    return git(setup.origin, "rev-parse", "main")


def is_detached(tree: Path) -> bool:
    return run_git(tree, "symbolic-ref", "-q", "HEAD", check=False).returncode != 0


def reject_every_push(origin: Path) -> None:
    """A hook that refuses each push and appends a line to `attempts` for it."""
    hook = origin / "hooks" / "pre-receive"
    hook.write_text(
        f"#!/bin/sh\necho x >> {origin / 'attempts'}\necho 'remote says no' >&2\nexit 1\n"
    )
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)


def test_a_phase_s_commit_is_made_on_the_detached_head_and_pushed_to_the_default_branch(
    tmp_path: Path,
) -> None:
    setup, inst = pipeline(tmp_path)
    recorded = git(setup.worktree, "rev-parse", "HEAD")

    assert phase(inst, doing(inst)) == 0

    assert is_detached(setup.worktree)
    assert git(setup.worktree, "rev-parse", "HEAD~1") == recorded
    assert git(setup.worktree, "show", "--name-only", "--format=", "HEAD").splitlines() == [
        log_name(inst)
    ]
    assert origin_main(setup) == git(setup.worktree, "rev-parse", "HEAD")
    assert git(setup.working_copy, "symbolic-ref", "--short", "HEAD") == "feature"


def test_a_phase_that_leaves_head_on_a_branch_ends_detached_at_the_recorded_head(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    setup, inst = pipeline(tmp_path)
    worktree = setup.worktree
    recorded = git(worktree, "rev-parse", "HEAD")

    def switch() -> None:
        git(worktree, "checkout", "-q", "-b", "stray-branch")
        commit(worktree, "stray.txt")

    assert phase(inst, doing(inst, switch)) == 0

    assert is_detached(worktree)
    assert git(worktree, "rev-parse", "HEAD~1") == recorded
    assert git(worktree, "branch", "--list", "stray-branch") != "", "the stray branch is kept"
    assert "stray-branch" in capsys.readouterr().out
    assert git(worktree, "show", "--name-only", "--format=", "HEAD").splitlines() == [
        log_name(inst)
    ]
    assert origin_main(setup) == git(worktree, "rev-parse", "HEAD")


def test_a_head_that_no_longer_contains_the_recorded_head_stops_the_run_and_commits_nothing(
    tmp_path: Path,
) -> None:
    setup, inst = pipeline(tmp_path)
    worktree = setup.worktree
    pushed = origin_main(setup)

    def rewrite() -> None:
        git(worktree, "checkout", "-q", "--orphan", "rewrite")
        commit(worktree, "unrelated.txt")

    assert phase(inst, doing(inst, rewrite)) == runner.STOPPED

    assert origin_main(setup) == pushed
    assert git(worktree, "log", "-1", "--format=%s") == "write unrelated.txt"
    assert git(worktree, "rev-list", "--count", "HEAD") == "1"
    assert git(setup.working_copy, "rev-parse", "main") == pushed


def test_a_rejected_push_fetches_and_rebases_once_and_pushes_again(tmp_path: Path) -> None:
    setup, inst = pipeline(tmp_path)
    worktree = setup.worktree
    (worktree / "runs" / "units.json").write_text('["pipeline state"]\n')

    def someone_else_pushes() -> None:
        publish_elsewhere(setup, {"theirs.md": "theirs\n"})

    assert phase(inst, doing(inst, someone_else_pushes)) == 0

    assert is_detached(worktree)
    assert origin_main(setup) == git(worktree, "rev-parse", "HEAD")
    assert git(worktree, "show", "HEAD:theirs.md") == "theirs"
    assert git(worktree, "show", f"HEAD:{log_name(inst)}")
    assert (worktree / "runs" / "units.json").read_text() == '["pipeline state"]\n'


def test_a_second_rejection_is_reported_with_the_commit_kept(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    setup, inst = pipeline(tmp_path)
    worktree = setup.worktree
    assert setup.origin is not None
    origin = setup.origin

    def someone_else_pushes_and_the_remote_closes() -> None:
        publish_elsewhere(setup, {"theirs.md": "theirs\n"})
        reject_every_push(origin)

    assert phase(inst, doing(inst, someone_else_pushes_and_the_remote_closes)) == 0

    assert len((origin / "attempts").read_text().splitlines()) == 1, (
        "the first push is refused as non-fast-forward; the retry reaches the hook"
    )
    assert "rejected twice" in capsys.readouterr().out
    assert git(worktree, "log", "-1", "--format=%s").startswith("track:")
    theirs = git(origin, "rev-parse", "main")
    rebased = run_git(worktree, "merge-base", "--is-ancestor", theirs, "HEAD", check=False)
    assert rebased.returncode == 0


def test_a_rebase_that_conflicts_is_aborted_and_reported_with_the_commit_kept(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    setup, inst = pipeline(tmp_path)
    worktree = setup.worktree
    notes = "runs/tracked-issues.md"
    publish_elsewhere(setup, {notes: "base\n"}, "notes")
    git(worktree, "merge", "--ff-only", "origin/main")
    recorded = git(worktree, "rev-parse", "HEAD")

    def edits_notes_while_someone_else_does() -> None:
        (worktree / notes).write_text("ours\n")
        publish_elsewhere(setup, {notes: "theirs\n"}, "theirs")

    assert phase(inst, doing(inst, edits_notes_while_someone_else_does)) == 0

    assert "rejected twice" in capsys.readouterr().out
    assert git(worktree, "log", "-1", "--format=%s").startswith("track:")
    assert git(worktree, "rev-parse", "HEAD~1") == recorded
    git_dir = Path(git(worktree, "rev-parse", "--path-format=absolute", "--git-dir"))
    assert not (git_dir / "rebase-merge").exists()
    assert not (git_dir / "rebase-apply").exists()
    assert git(worktree, "log", "-1", "--format=%s", origin_main(setup)) == "theirs"
