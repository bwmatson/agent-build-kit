"""A step reads the git directory as a directory, so a file git replaces by rename stays
readable, and cannot run anything in it (spec: sandbox-git-rewrites)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.sandboxes.policy import git_parts
from tests.factories import commit, git, init_repo
from tests.sandboxes.git_dir_enforcing import Enforcing, replace_as_git_does
from tests.sandboxes.policy_support import Scene


@pytest.fixture
def linked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Scene:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    (tmp_path / "home").mkdir()
    scene = Scene(tmp_path)
    init_repo(scene.main)
    commit(scene.main, "a.txt")
    git(scene.main, "worktree", "add", "-q", "-b", "unit", str(scene.worktree))
    git(scene.main, "pack-refs", "--all")
    return scene


def opened(scene: Scene) -> list[Path]:
    """What `git` opens to run in the linked worktree."""
    common = scene.main / ".git"
    entry = common / "worktrees" / scene.worktree.name
    return [
        common / "HEAD",
        common / "packed-refs",
        common / "config",
        common / "objects",
        entry / "HEAD",
        entry / "gitdir",
        entry / "commondir",
        scene.worktree / ".git",
    ]


def run_git(scene: Scene) -> None:
    git(scene.worktree, "status")
    git(scene.worktree, "log", "-1")
    git(scene.worktree, "diff", "main...HEAD")


def test_the_common_git_directory_is_read_as_a_directory(linked: Scene) -> None:
    common = (linked.main / ".git").resolve()

    policy = linked.policy()

    assert common in policy.read
    assert (linked.worktree / ".git").resolve() in policy.read
    assert not [p for p in policy.read if p.parent == common], "no single file in it is listed"


def test_git_reads_survive_packed_refs_and_head_being_replaced(linked: Scene) -> None:
    run_git(linked)
    policy = linked.policy()
    before = Enforcing(policy)
    assert all(before.can_read(p) for p in opened(linked)), "the control: all read to begin with"

    for name in ("packed-refs", "HEAD"):
        replace_as_git_does(linked.main / ".git" / name)

    after = Enforcing(policy)
    refused = [p for p in opened(linked) if not after.can_read(p)]
    assert refused == []
    run_git(linked)


def test_a_hook_is_readable_and_not_executable_and_the_write_list_is_unchanged(
    linked: Scene,
) -> None:
    hook = linked.main / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text("#!/bin/sh\nexit 0\n")
    hook.chmod(0o755)

    policy = linked.policy()
    step = Enforcing(policy)

    assert step.can_read(hook)
    assert not step.can_execute(hook)
    assert policy.write == (linked.worktree.resolve(), *git_parts(linked.worktree))


def test_a_sibling_repository_stays_unreadable(linked: Scene) -> None:
    other = init_repo(linked.tmp / "other")
    commit(other, "b.txt")

    step = Enforcing(linked.policy())

    assert step.can_read(linked.main / ".git" / "HEAD"), "the control: its own is read"
    assert not step.can_read(other / ".git" / "config")
    assert not step.can_read(other / "b.txt")
    assert step.can_read(linked.main / ".git" / "config") and not step.can_execute(
        linked.main / ".git" / "config"
    )
