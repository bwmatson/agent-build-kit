"""The kit does not fight the forge's retarget and rebase of a stack merged at once.

The forge may already have moved a child's pull request onto the default branch and rebased its
branch. A restack does not retarget a pull request whose base already matches, a child branch the
forge rebased with the kit's own patch-ids is adopted by the push without pushing or forcing, and
a remote with different changes still meets the lease push and its failure. Real git and a bare
remote stand in for the code host's branches; the forge answers are hand-written.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.restack import StaleRemote
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED, base_of
from agent_build_kit.pipeline.wiring import build_push
from tests.factories import commit, git
from tests.pipeline.test_retarget_retry import CHILD, WANTED_BASE
from tests.pipeline.test_satisfied_release import World

PARENT = "feature/1"
PARENT_BRANCH, CHILD_BRANCH = f"spec/{PARENT}", f"spec/{CHILD}"


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    """The parent, of two commits, squash-merged into main, its child in review, approved and
    pushed."""
    world = World(tmp_path, monkeypatch)
    world.branch(PARENT_BRANCH, "main", file="one.txt")
    git(world.repo, "checkout", "-q", PARENT_BRANCH)
    world.commit("one-more.txt")
    git(world.repo, "push", "-q", "origin", PARENT_BRANCH)
    git(world.repo, "checkout", "-q", "main")
    world.branch(CHILD_BRANCH, PARENT_BRANCH, file="two.txt")
    git(world.repo, "merge", "--squash", PARENT_BRANCH)
    git(world.repo, "commit", "-qm", "feature 1 (squashed)")
    git(world.repo, "push", "-q", "origin", "main")
    world.add(PARENT, MERGED, pr=1)
    world.add(CHILD, IN_REVIEW, PARENT, pr=2)
    return world


def host_clone(world: World, tmp_path: Path) -> Path:
    other = tmp_path / "host"
    subprocess.run(["git", "clone", "-q", str(world.remote), str(other)], check=True)
    git(other, "config", "user.email", "o@o.o")
    git(other, "config", "user.name", "o")
    git(other, "checkout", "-q", CHILD_BRANCH)
    return other


def forge_rebases_the_child(world: World, tmp_path: Path, *, trunk_ahead: bool = False) -> str:
    """The forge rebases the child's branch onto main, as it does above a merged pull request,
    and force-pushes it: the same change in a new commit. With `trunk_ahead`, main on the host
    first gains a commit the local clone has not fetched. Returns the new head."""
    other = host_clone(world, tmp_path)
    if trunk_ahead:
        git(other, "checkout", "-q", "main")
        commit(other, "elsewhere.txt")
        git(other, "push", "-q", "origin", "main")
        git(other, "checkout", "-q", CHILD_BRANCH)
    git(other, "rebase", "-q", "--onto", "origin/main", f"origin/{PARENT_BRANCH}", CHILD_BRANCH)
    git(other, "push", "-q", "--force", "origin", CHILD_BRANCH)
    return git(other, "rev-parse", "HEAD")


def remote_head(world: World, branch: str) -> str:
    return git(world.remote, "rev-parse", f"refs/heads/{branch}")


def push_outcome(push: Callable[..., str], repo: Path) -> str | None:
    """Push the child's branch; the name of what it raised, or None when it returned."""
    try:
        push(CHILD_BRANCH, cwd=repo)
    except RuntimeError as error:
        return type(error).__name__
    return None


def restack_child(world: World, retargets: list[int]) -> object:
    """Restack the child; recording stand-ins take the host's retarget and push."""
    restack = events.build_restack(
        repos={"app": world.repo},
        store=world.store,
        root=world.trees,
        unit_test=lambda **k: (True, ""),
        comment=lambda *a, **k: None,
        retarget=lambda pr, base, **k: retargets.append(pr),
        push=lambda repo, branch, *, last_pushed: "",
    )
    return restack(
        branch=CHILD_BRANCH,
        old_base=PARENT_BRANCH,
        new_base=base_of(world.store.get(CHILD), world.store.all()),
        child=world.store.get(CHILD),
        parent=world.store.get(PARENT),
    )


def test_a_restack_does_not_retarget_a_pull_request_the_forge_already_moved(
    world: World,
) -> None:
    world.forge.bases[2] = (CHILD_BRANCH, WANTED_BASE)
    retargets: list[int] = []

    restack_child(world, retargets)

    assert retargets == []


@pytest.mark.parametrize("trunk_ahead", [False, True])
def test_a_child_branch_the_forge_rebased_with_the_same_changes_is_adopted_without_a_push(
    world: World, tmp_path: Path, trunk_ahead: bool
) -> None:
    rebased = forge_rebases_the_child(world, tmp_path, trunk_ahead=trunk_ahead)
    pushes: list[str | None] = []

    raised = push_outcome(
        build_push(
            world.store, push=lambda repo, branch, last_pushed: pushes.append(last_pushed) or ""
        ),
        world.repo,
    )

    unit = world.store.get(CHILD)
    assert (
        raised,
        pushes,
        world.sha(CHILD_BRANCH),
        remote_head(world, CHILD_BRANCH),
        unit.approved,
        unit.pushed,
    ) == (None, [], rebased, rebased, rebased, rebased)


def test_a_remote_branch_with_different_changes_still_gets_the_lease_push_and_its_failure(
    world: World, tmp_path: Path
) -> None:
    other = host_clone(world, tmp_path)
    commit(other, "someone-else.txt")
    git(other, "push", "-q", "origin", CHILD_BRANCH)
    elsewhere = remote_head(world, CHILD_BRANCH)

    raised = push_outcome(build_push(world.store), world.repo)

    assert (raised, remote_head(world, CHILD_BRANCH)) == (StaleRemote.__name__, elsewhere)
