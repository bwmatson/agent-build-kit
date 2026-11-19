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
    # A fast-forward ignores --no-commit: the branch moves to main's tip without a commit.
    "git merge --no-commit main",
    "git merge -n main",
    "git merge main -m --quit",
    "git cherry-pick -x abc123",
    "git rebase --abort -x",
    "git -c user.name=x commit -m y",
    "git reset -q --hard HEAD~1",
    "git checkout -B x abc123",
    "git switch -C x abc123",
    "git branch -f main abc123",
    "git symbolic-ref HEAD refs/heads/x",
    "git filter-branch --all",
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
    "git merge --no-ff --no-commit main",
    "git merge --squash main",
    "git cherry-pick -nx abc123",
    "git cherry-pick -xn abc123",
    "git symbolic-ref HEAD",
    "git checkout -b x",
    "git switch -c x",
    "git branch -a",
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


# What a step that holds a rewrite request may run, and what it still may not (spec:
# implement-may-rewrite-its-own-commits).
REWRITES = [
    'git commit -m "test: split"',
    "git commit --amend --no-edit",
    "git commit -C abc123",
    "git rebase HEAD~3",
    "git rebase --continue",
    "git cherry-pick abc123",
    "git revert abc123",
    "git reset --soft HEAD~2",
    "git reset --mixed abc123",
    "git add -A && git commit -m x",
    "git -C wt rebase main",
]

STILL_REFUSED = [
    ("git commit --no-verify -m x", "--no-verify"),
    ("git commit -n -m x", "--no-verify"),
    ("git merge main", "merge"),
    ("git pull", "pull"),
    ("git am fix.patch", "am"),
    ("git commit-tree HEAD^{tree} -m x", "commit-tree"),
    ("git update-ref refs/heads/x abc", "update-ref"),
    ("git filter-branch --all", "filter-branch"),
    ("git filter-repo --path a", "filter-repo"),
    ("git reset --hard HEAD~1", "--hard"),
    ("git reset --keep abc123", "--keep"),
    ("git reset --merge abc123", "--merge"),
    ("git add -A && git commit --no-verify -m x", "--no-verify"),
    ("git rebase main && git merge other", "merge"),
    ('git rebase -x "git commit --amend --no-edit --no-verify" HEAD~1', "--exec"),
    ("git rebase --exec='git push origin HEAD' HEAD~1", "--exec"),
    ("git rebase --exec 'make' HEAD~1", "--exec"),
    ("git rebase --ex 'make' HEAD~1", "--exec"),
    ("git rebase -ix make HEAD~1", "--exec"),
    ("git -c sequence.editor='sh -c x' rebase -i HEAD~2", "editor"),
    ("git -c core.editor=./evil commit --amend", "editor"),
    ("GIT_SEQUENCE_EDITOR='sh x' git rebase -i HEAD~2", "editor"),
    ("env GIT_EDITOR=./evil git commit --amend", "editor"),
]


@pytest.mark.parametrize("command", REWRITES)
def test_a_step_with_a_rewrite_request_may_rewrite_the_units_commits(command: str) -> None:
    assert check_no_commit(command, rewrite=True).allowed


@pytest.mark.parametrize(("command", "named"), STILL_REFUSED)
def test_a_step_with_a_rewrite_request_is_refused_what_the_spec_keeps_refused(
    command: str, named: str
) -> None:
    # The same step opens the amend, so the refusal below is the narrowed list and not a blanket.
    assert check_no_commit("git commit --amend --no-edit", rewrite=True).allowed

    verdict = check_no_commit(command, rewrite=True)

    assert not verdict.allowed
    assert named in verdict.reason


@pytest.mark.parametrize("command", REWRITES)
def test_a_step_with_no_rewrite_request_is_refused_every_rewrite_command(command: str) -> None:
    # The request is what opens the command: the same command is allowed with it, refused without.
    assert check_no_commit(command, rewrite=True).allowed

    assert not check_no_commit(command).allowed
    assert not check_no_commit(command, rewrite=False).allowed
