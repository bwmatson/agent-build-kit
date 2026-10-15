"""The one routine that syncs the pipeline worktree to the default branch tip, and what stops it."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.planning_sync import SyncOutcome, sync_planning
from agent_build_kit.pipeline.shell import git as run_git
from tests.factories import commit, commit_files, git, init_repo
from tests.planning_worktree_support import InRepo, in_repo, installation_at, publish_elsewhere


class Said:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, line: str) -> None:
        self.lines.append(line)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def sync(setup: InRepo, **overrides):
    said = Said()
    inst = installation_at(setup.worktree, setup.working_copy, **overrides)
    return sync_planning(inst, said), said


def state_of(tree: Path) -> dict[str, str]:
    """What a tree holds that a sync must not change on its own: HEAD, the branch it is on, the
    index, and the status with every untracked file."""
    return {
        "head": git(tree, "rev-parse", "HEAD"),
        "branch": run_git(tree, "symbolic-ref", "-q", "HEAD", check=False).stdout,
        "index": run_git(tree, "diff", "--cached").stdout,
        "status": run_git(tree, "status", "--porcelain", "--untracked-files=all").stdout,
    }


def advance_by_two(setup: InRepo) -> str:
    publish_elsewhere(setup, {"a.txt": "a\n"}, "first")
    return publish_elsewhere(setup, {"b.txt": "b\n"}, "second")


def test_a_worktree_behind_moves_to_the_tip_and_keeps_its_modification(tmp_path: Path) -> None:
    setup = in_repo(tmp_path)
    git(setup.working_copy, "checkout", "-q", "-b", "feature")
    (setup.working_copy / "README.md").write_text("edited by a person\n")
    (setup.working_copy / "notes.txt").write_text("untracked\n")
    git(setup.working_copy, "add", "notes.txt")
    tip = advance_by_two(setup)
    (setup.worktree / "runs" / "units.json").write_text('["pipeline state"]\n')
    person_before = state_of(setup.working_copy)
    contents = (setup.working_copy / "README.md").read_text()

    result, _ = sync(setup)

    assert result.outcome == SyncOutcome.SYNCED
    assert git(setup.worktree, "rev-parse", "HEAD") == tip
    assert (setup.worktree / "runs" / "units.json").read_text() == '["pipeline state"]\n'
    assert (setup.worktree / "b.txt").exists()
    assert state_of(setup.working_copy) == person_before
    assert (setup.working_copy / "README.md").read_text() == contents


def test_a_worktree_at_the_tip_is_current_and_unchanged(tmp_path: Path) -> None:
    setup = in_repo(tmp_path)
    (setup.worktree / "runs" / "units.json").write_text('["pipeline state"]\n')
    before = state_of(setup.worktree)

    result, _ = sync(setup)

    assert result.outcome == SyncOutcome.CURRENT
    assert state_of(setup.worktree) == before


def test_a_worktree_ahead_of_the_tip_is_logged_and_left(tmp_path: Path) -> None:
    setup = in_repo(tmp_path)
    git(setup.worktree, "config", "user.email", "t@t.t")
    git(setup.worktree, "config", "user.name", "t")
    commit(setup.worktree, "bookkeeping.md")
    before = state_of(setup.worktree)

    result, said = sync(setup)

    assert result.outcome == SyncOutcome.AHEAD
    assert "ahead" in said.text
    assert state_of(setup.worktree) == before


def test_a_repository_with_no_origin_moves_to_the_local_default_branch(tmp_path: Path) -> None:
    setup = in_repo(tmp_path, origin=False)
    tip = commit(setup.working_copy, "local.txt")

    result, _ = sync(setup)

    assert result.outcome == SyncOutcome.SYNCED
    assert git(setup.worktree, "rev-parse", "HEAD") == tip
    common = Path(git(setup.worktree, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    assert not (common / "FETCH_HEAD").exists()


def test_a_diverged_worktree_is_stopped_with_both_commits_intact(tmp_path: Path) -> None:
    setup = in_repo(tmp_path)
    git(setup.worktree, "config", "user.email", "t@t.t")
    git(setup.worktree, "config", "user.name", "t")
    own = commit(setup.worktree, "own.md")
    publish_elsewhere(setup, {"theirs.md": "theirs\n"})
    before = state_of(setup.worktree)

    result, _ = sync(setup)

    assert result.outcome == SyncOutcome.STOPPED
    assert "diverged" in result.reason
    assert state_of(setup.worktree) == before
    assert git(setup.worktree, "rev-parse", "HEAD") == own


def test_a_new_commit_on_a_modified_file_stops_with_gits_reason(tmp_path: Path) -> None:
    setup = in_repo(tmp_path)
    publish_elsewhere(setup, {"runs/units.json": '["theirs"]\n'})
    (setup.worktree / "runs" / "units.json").write_text('["pipeline state"]\n')
    before = state_of(setup.worktree)

    result, _ = sync(setup)

    assert result.outcome == SyncOutcome.STOPPED
    assert "units.json" in result.reason
    assert state_of(setup.worktree) == before
    assert (setup.worktree / "runs" / "units.json").read_text() == '["pipeline state"]\n'
    assert git(setup.worktree, "stash", "list") == ""


def test_an_untracked_file_in_the_merges_way_stops_and_is_kept(tmp_path: Path) -> None:
    setup = in_repo(tmp_path)
    publish_elsewhere(setup, {"runs/log.md": "published\n"})
    (setup.worktree / "runs" / "log.md").write_text("the pipeline's own\n")
    before = state_of(setup.worktree)

    result, _ = sync(setup)

    assert result.outcome == SyncOutcome.STOPPED
    assert "log.md" in result.reason
    assert state_of(setup.worktree) == before
    assert (setup.worktree / "runs" / "log.md").read_text() == "the pipeline's own\n"


def test_head_on_a_branch_is_stopped_naming_the_branch_and_keeps_it(tmp_path: Path) -> None:
    setup = in_repo(tmp_path)
    git(setup.worktree, "checkout", "-q", "-b", "agent-work")
    publish_elsewhere(setup, {"a.txt": "a\n"})
    before = state_of(setup.worktree)

    result, _ = sync(setup)

    assert result.outcome == SyncOutcome.STOPPED
    assert "agent-work" in result.reason
    assert state_of(setup.worktree) == before
    assert git(setup.worktree, "rev-parse", "--verify", "agent-work")


@pytest.mark.parametrize(
    ("name", "is_directory"),
    [
        ("MERGE_HEAD", False),
        ("rebase-merge", True),
        ("rebase-apply", True),
        ("CHERRY_PICK_HEAD", False),
        ("REVERT_HEAD", False),
    ],
)
def test_an_unfinished_operation_is_stopped_and_touches_nothing(
    tmp_path: Path, name: str, is_directory: bool
) -> None:
    setup = in_repo(tmp_path)
    publish_elsewhere(setup, {"a.txt": "a\n"})
    git_dir = Path(git(setup.worktree, "rev-parse", "--path-format=absolute", "--git-dir"))
    marker = git_dir / name
    if is_directory:
        marker.mkdir()
    else:
        marker.write_text(git(setup.worktree, "rev-parse", "HEAD") + "\n")
    before = state_of(setup.worktree)

    result, _ = sync(setup)

    assert result.outcome == SyncOutcome.STOPPED
    assert result.reason
    assert state_of(setup.worktree) == before
    assert marker.exists()


def test_self_pull_off_skips_and_says_so(tmp_path: Path) -> None:
    setup = in_repo(tmp_path)
    publish_elsewhere(setup, {"a.txt": "a\n"})
    before = state_of(setup.worktree)

    result, said = sync(setup, planning={"self_pull": False})

    assert result.outcome == SyncOutcome.SKIPPED
    assert "off" in said.text
    assert state_of(setup.worktree) == before


def test_a_separate_root_is_put_on_the_default_branch_and_pulled(tmp_path: Path) -> None:
    setup = in_repo(tmp_path)
    planning = setup.working_copy
    code = init_repo(tmp_path / "code")
    commit_files(code, "start", {"README.md": "code\n"})
    git(planning, "checkout", "-q", "-b", "elsewhere")
    publish_elsewhere(setup, {"a.txt": "a\n"})
    said = Said()

    sync_planning(installation_at(planning, code), said)

    assert git(planning, "symbolic-ref", "--short", "HEAD") == "main"
    assert (planning / "a.txt").exists()
    assert "elsewhere" in said.text
    assert git(planning, "rev-parse", "--verify", "elsewhere")
