"""`check_no_commit`: a turn that may not commit makes no commit and moves no branch, because the
commit is what feeds the pipeline and the pipeline (or the person) makes it (spec:
build-agent-does-not-commit)."""

import pytest

from agent_build_kit.pipeline.command_policy import check_no_commit

COMMITS = [
    'git commit -m "fix"',
    "git commit --amend --no-edit",
    "git commit --no-verify -m x",
    "git -C wt commit -am wip",
    "env GIT_AUTHOR_NAME=x git commit -m x",
    "git add -A && git commit -m x",
    "git add -A && git commit --no-verify -m x",
    "git status; git commit -m x",
]

# What makes a commit or moves a branch without being `git commit`.
MOVES = [
    "git cherry-pick abc123",
    "git cherry-pick --continue",
    "git cherry-pick --skip",
    "git revert HEAD",
    "git merge main",
    "git merge --continue",
    "git rebase main",
    "git rebase --continue",
    "git rebase --skip",
    "git am fix.patch",
    "git pull",
    "git commit-tree HEAD^{tree} -m x",
    "git update-ref HEAD abc123",
    "git reset --hard HEAD~1",
    "git reset --soft HEAD~1",
    "git reset --mixed abc123",
    "git reset --keep abc123",
    "git reset HEAD~1",
    "git reset abc123",
    "git reset src/a.py",
    "git -C wt rebase main",
    "env GIT_EDITOR=true git rebase --continue",
    "git status && git rebase main",
]

# What leaves its result in the working tree, and the cleanups that make no commit.
KEPT = [
    "git status",
    "git add -A",
    "git diff --stat",
    "git log --oneline",
    "git show HEAD",
    "echo git commit",
    "git restore --staged a.py",
    "git restore a.py",
    "git stash",
    "git reset",
    "git reset -- src/a.py",
    "git cherry-pick -n abc123",
    "git cherry-pick --no-commit abc123",
    "git revert -n HEAD",
    "git merge --no-commit main",
    "git cherry-pick --abort",
    "git cherry-pick --quit",
    "git merge --abort",
    "git rebase --abort",
    "git rebase --quit",
    "git apply fix.patch",
]


@pytest.mark.parametrize("command", [*COMMITS, *MOVES])
def test_no_commit_refuses_every_command_that_makes_or_moves_a_commit(command: str) -> None:
    verdict = check_no_commit(command)

    assert not verdict.allowed
    assert verdict.reason


@pytest.mark.parametrize("command", KEPT)
def test_no_commit_leaves_what_stays_in_the_working_tree_alone(command: str) -> None:
    assert check_no_commit(command).allowed


def test_the_reason_says_the_pipeline_commits_and_the_changes_stay_in_the_tree() -> None:
    reason = check_no_commit("git commit -m x").reason

    assert "pipeline" in reason
    assert "working tree" in reason
