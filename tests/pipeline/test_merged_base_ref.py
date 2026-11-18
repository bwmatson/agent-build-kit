"""A merged parent's remote branch is deleted and its head kept as a local ref.

With `delete_merged_branches` on, a merge deletes the parent's remote branch when units are
stacked on it and keeps its last head under `refs/abk/bases/<branch>`, which the children's
restacks use once the branch is gone. The tests run the real release and restack against real
git repositories and a bare remote, with the stand-in forge as the code host.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import config as config_module
from agent_build_kit import forges
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.events import RestackOutcome
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED, base_of
from tests.factories import git
from tests.forges.stand_in import lookup
from tests.pipeline.test_satisfied_release import RecordingForge, World

PARENT, CHILD = "feature/1", "feature/2"
PARENT_BRANCH, CHILD_BRANCH = f"spec/{PARENT}", f"spec/{CHILD}"
BASE_REF = f"refs/abk/bases/{PARENT_BRANCH}"


class AzureStandIn(RecordingForge):
    """A host that neither deletes head branches nor retargets what was stacked on them."""

    name = "azure_devops"


def squash_merged(world: World) -> None:
    """The parent reaches the default branch as one new commit, as a squash merge makes it."""
    git(world.repo, "merge", "--squash", PARENT_BRANCH)
    git(world.repo, "commit", "-qm", "feature 1 (squashed)")
    git(world.repo, "push", "-q", "origin", "main")


def stacked(world: World) -> World:
    """The parent merged by squash, the child in review on the parent's branch."""
    world.branch(PARENT_BRANCH, "main", file="one.txt")
    world.branch(CHILD_BRANCH, PARENT_BRANCH, file="two.txt")
    squash_merged(world)
    world.add(PARENT, MERGED, pr=1)
    world.add(CHILD, IN_REVIEW, PARENT, pr=2)
    return world


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    return stacked(World(tmp_path, monkeypatch))


@pytest.fixture
def azure_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    world = World(tmp_path, monkeypatch)
    world.forge = AzureStandIn(world.order)
    monkeypatch.setattr(forges, "for_repo", lookup(world.forge))
    return stacked(world)


def setting(*, on: bool) -> None:
    current = config_module.active()
    repos = {
        name: repo.model_copy(update={"delete_merged_branches": on})
        for name, repo in current.repos.items()
    }
    config_module.activate(current.model_copy(update={"repos": repos}), config_module.active_root())


def kept_head(world: World) -> str | None:
    return git(world.repo, "for-each-ref", "--format=%(objectname)", BASE_REF).strip() or None


def release(world: World) -> None:
    world.release(PARENT, repos={"app": world.repo})


def gone_from_the_host(world: World) -> None:
    """The branch deleted as the host deletes it: from the remote, and here with its worktree."""
    git(world.repo, "push", "-q", "origin", "--delete", PARENT_BRANCH)
    git(world.repo, "branch", "-q", "-D", PARENT_BRANCH)


def restack_child(world: World, **overrides) -> RestackOutcome | None:
    restack = events.build_restack(
        repos={"app": world.repo},
        store=world.store,
        root=world.trees,
        unit_test=lambda **k: (True, ""),
        comment=lambda *a, **k: None,
        **overrides,
    )
    return restack(
        branch=CHILD_BRANCH,
        old_base=PARENT_BRANCH,
        new_base=base_of(world.store.get(CHILD), world.store.all()),
        child=world.store.get(CHILD),
        parent=world.store.get(PARENT),
    )


# --- the branch is deleted and its head kept ---------------------------------------


def test_a_merge_deletes_the_parents_remote_branch_when_a_unit_is_stacked_on_it(
    world: World,
) -> None:
    release(world)

    assert world.forge.deleted == [PARENT_BRANCH]


def test_a_merge_keeps_the_parents_last_head_under_a_local_ref(world: World) -> None:
    head = world.sha(PARENT_BRANCH)

    release(world)

    assert kept_head(world) == head


def test_a_merge_with_nothing_stacked_on_it_deletes_no_branch_and_keeps_no_ref(
    world: World,
) -> None:
    world.store.set_state(CHILD, MERGED)

    release(world)
    with_no_child = (list(world.forge.deleted), kept_head(world))
    world.store.set_state(CHILD, IN_REVIEW)
    release(world)

    assert with_no_child == ([], None)
    assert world.forge.deleted == [PARENT_BRANCH]


def test_a_forge_that_deletes_merged_branches_itself_is_not_asked_to_but_the_ref_is_kept(
    world: World,
) -> None:
    world.forge.deletes_head_branch_on_merge = True

    release(world)

    assert world.forge.deleted == []
    assert kept_head(world) == world.sha(PARENT_BRANCH)


def test_with_the_setting_off_nothing_is_deleted_and_no_ref_is_kept(world: World) -> None:
    setting(on=False)

    release(world)
    when_off = (list(world.forge.deleted), kept_head(world))
    setting(on=True)
    release(world)

    assert when_off == ([], None)
    assert world.forge.deleted == [PARENT_BRANCH]


# --- the ref is removed with the branch ---------------------------------------------


def test_the_ref_stays_while_a_child_is_owed_its_move_and_goes_when_none_is(
    world: World,
) -> None:
    release(world)

    def pass_over() -> None:
        events.remove_satisfied(
            world.store.get(PARENT),
            store=world.store,
            claim=events.build_claim(world.locks),
            remove_worktree=lambda repo, branch: None,
            delete_branch=lambda repo, branch: None,
            on_new_base=lambda child: True,
            repos={"app": world.repo},
            log=lambda line: None,
        )

    pass_over()
    still_owed = kept_head(world)
    world.store.set_state(CHILD, IN_REVIEW)
    pass_over()

    assert still_owed is not None
    assert kept_head(world) is None


# --- the child's restack ------------------------------------------------------------


def test_a_childs_restack_uses_the_local_ref_when_the_parents_branch_is_gone(
    world: World,
) -> None:
    release(world)
    gone_from_the_host(world)

    outcome = restack_child(world)

    assert outcome is not RestackOutcome.CONFLICT
    assert world.own_commits(CHILD_BRANCH, "origin/main") == ["add two.txt"]


def test_a_child_the_forge_already_rebased_is_neither_rewritten_nor_pushed(
    world: World,
) -> None:
    release(world)
    gone_from_the_host(world)
    # What the forge did: the child rebased onto the default branch and force-pushed.
    git(world.repo, "checkout", "-q", "-B", CHILD_BRANCH, "main")
    world.commit("two.txt")
    git(world.repo, "push", "-q", "--force", "origin", CHILD_BRANCH)
    git(world.repo, "checkout", "-q", "main")
    rebased = world.sha(CHILD_BRANCH)
    world.store.record_push(CHILD, rebased)
    pushes: list[tuple] = []

    outcome = restack_child(world, push=lambda *a, **k: pushes.append((a, k)) or rebased)

    assert outcome is RestackOutcome.UNMOVED
    assert world.sha(CHILD_BRANCH) == rebased
    assert pushes == []


def test_on_a_host_that_does_not_retarget_the_explicit_retarget_still_runs(
    azure_world: World,
) -> None:
    release(azure_world)
    gone_from_the_host(azure_world)

    restack_child(azure_world)

    assert azure_world.forge.deleted == [PARENT_BRANCH]
    assert (2, "main") in azure_world.forge.retargeted()
