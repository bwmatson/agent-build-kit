"""`check_no_commit`: a turn the server runs commits nothing, because the commit is what feeds
the pipeline and the person makes it."""

import pytest

from agent_build_kit.pipeline.command_policy import check_no_commit


@pytest.mark.parametrize(
    "command",
    [
        'git commit -m "fix"',
        "git commit --amend --no-edit",
        "git -C wt commit -am wip",
        "env GIT_AUTHOR_NAME=x git commit -m x",
        "git add -A && git commit -m x",
        "git status; git commit -m x",
    ],
)
def test_no_commit_refuses_every_commit(command: str) -> None:
    verdict = check_no_commit(command)

    assert not verdict.allowed
    assert verdict.reason


@pytest.mark.parametrize(
    "command",
    [
        "git status",
        "git add -A",
        "git diff --stat",
        "git log --oneline",
        "echo git commit",
        "git restore --staged a.py",
    ],
)
def test_no_commit_leaves_other_commands_alone(command: str) -> None:
    assert check_no_commit(command).allowed
