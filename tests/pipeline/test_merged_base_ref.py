"""A merged parent's remote branch is deleted and its head kept as a local ref.

With `delete_merged_branches` on, a merge deletes the parent's remote branch when units are
stacked on it and keeps its last head under `refs/abk/bases/<branch>`, which the children's
restacks use once the branch is gone. The tests run the real release and restack against real
git repositories and a bare remote, with the stand-in forge as the code host.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from agent_build_kit import config as config_module
from agent_build_kit import forges
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.events import RestackOutcome
from agent_build_kit.pipeline.units import (
    CLOSED,
    IN_REVIEW,
    MERGED,
    SATISFIED,
    UnitState,
    base_of,
)
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


def test_a_merge_with_nothing_stacked_on_it_deletes_the_remote_branch_and_keeps_no_ref(
    world: World,
) -> None:
    world.store.set_state(CHILD, MERGED)

    release(world)

    assert world.forge.deleted == [PARENT_BRANCH]
    assert kept_head(world) is None


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


# --- settling ends with a branch check, and each pass makes it ----------------------

REFUSAL = "the project forbids deleting branches"


class DeletingForge(RecordingForge):
    """A host that deletes the branch from the remote when asked, and can refuse."""

    remote: Path
    refusal: str = ""

    def delete_remote_branch(self, repo, branch: str) -> None:
        if self.refusal:
            raise RuntimeError(self.refusal)
        super().delete_remote_branch(repo, branch)
        git(self.remote, "branch", "-D", branch)


@pytest.fixture
def host(world: World, monkeypatch: pytest.MonkeyPatch) -> DeletingForge:
    forge = DeletingForge(world.order)
    forge.remote = world.remote
    forge.bases = world.forge.bases
    world.forge = forge
    monkeypatch.setattr(forges, "for_repo", lookup(forge))
    return forge


@pytest.fixture
def swept(world: World, host: DeletingForge) -> World:
    """The merged parent's branch left on the remote by a merge that did not delete it; the
    child's pull request is closed and gone, so nothing is stacked on it."""
    world.store.set_state(CHILD, CLOSED)
    host.bases.pop(2)
    return world


class Sweep:
    """One pass over the merged units, and what it asked of the checkout."""

    def __init__(self, world: World) -> None:
        self.world = world
        self.removed: list[str] = []
        self.deleted: list[str] = []
        self.dirty = ""

    def __call__(self) -> None:
        def remove_worktree(repo: str, branch: str) -> None:
            if self.dirty:
                raise RuntimeError(self.dirty)
            self.removed.append(branch)

        events.remove_merged_branches(
            self.world.store,
            repos={"app": self.world.repo},
            remove_worktree=remove_worktree,
            delete_branch=lambda repo, branch: self.deleted.append(branch),
            on_new_base=lambda child: True,
            log=lambda line: None,
        )


def on_the_remote(world: World) -> set[str]:
    listed = git(world.repo, "ls-remote", "--heads", "origin")
    return {line.split("refs/heads/", 1)[1] for line in listed.splitlines()}


def count_remote_reads(world: World) -> Path:
    """Route the remote's upload-pack through a script that logs each read of its branches."""
    log = world.remote.parent / "reads.log"
    script = world.remote.parent / "upload-pack.sh"
    script.write_text(f'#!/bin/sh\necho read >> "{log}"\nexec git-upload-pack "$@"\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    git(world.repo, "config", "remote.origin.uploadpack", str(script))
    log.touch()
    return log


def test_a_branch_a_merge_left_behind_is_deleted_everywhere_on_the_pass(swept: World) -> None:
    sweep = Sweep(swept)

    sweep()

    assert PARENT_BRANCH not in on_the_remote(swept)
    assert (sweep.removed, sweep.deleted) == ([PARENT_BRANCH], [PARENT_BRANCH])
    assert swept.store.get(PARENT).branch_kept == ""


def test_the_remotes_branches_are_read_once_however_many_merged_units_there_are(
    swept: World,
) -> None:
    swept.branch("spec/feature/3", "main", file="three.txt")
    swept.add("feature/3", MERGED, pr=3)
    reads = count_remote_reads(swept)

    Sweep(swept)()

    assert reads.read_text().splitlines() == ["read"]
    assert on_the_remote(swept) == {"main", CHILD_BRANCH}


def test_a_remote_branch_an_open_pull_request_targets_stays_until_it_is_retargeted(
    swept: World,
) -> None:
    swept.forge.bases[2] = (CHILD_BRANCH, PARENT_BRANCH)
    swept.store.set_state(CHILD, IN_REVIEW)
    sweep = Sweep(swept)

    sweep()
    while_targeted = on_the_remote(swept)
    swept.forge.bases[2] = (CHILD_BRANCH, "main")
    sweep()

    assert PARENT_BRANCH in while_targeted
    assert PARENT_BRANCH not in on_the_remote(swept)


def add_a_merged_sibling(world: World) -> str:
    """A merged unit whose branch a merge left on the remote, so a pass has work to do."""
    world.branch("spec/feature/3", "main", file="three.txt")
    world.add("feature/3", MERGED, pr=3)
    return "spec/feature/3"


@pytest.mark.parametrize("state", [CLOSED, SATISFIED, UnitState.RETIRED])
def test_the_branches_of_a_unit_that_did_not_merge_are_left_alone(
    swept: World, state: UnitState
) -> None:
    sibling = add_a_merged_sibling(swept)
    swept.store.set_state(PARENT, state)
    sweep = Sweep(swept)

    sweep()

    assert sibling not in on_the_remote(swept)
    assert PARENT_BRANCH in on_the_remote(swept)
    assert (sweep.removed, sweep.deleted) == ([sibling], [sibling])


def test_a_refused_deletion_does_not_fail_the_pass_is_stored_and_asked_again(
    swept: World, host: DeletingForge
) -> None:
    host.refusal = REFUSAL
    sweep = Sweep(swept)

    sweep()
    refused = swept.store.get(PARENT).branch_kept
    host.refusal = ""
    sweep()

    assert REFUSAL in refused
    assert PARENT_BRANCH not in on_the_remote(swept)
    assert swept.store.get(PARENT).branch_kept == ""


def test_a_worktree_with_uncommitted_changes_is_the_stored_reason_and_keeps_the_branch(
    swept: World,
) -> None:
    sweep = Sweep(swept)
    sweep.dirty = "worktree has uncommitted changes"

    sweep()

    assert "uncommitted changes" in swept.store.get(PARENT).branch_kept
    assert sweep.deleted == []


def test_with_the_setting_off_the_pass_deletes_nothing_and_on_it_does(swept: World) -> None:
    setting(on=False)
    sweep = Sweep(swept)

    sweep()
    while_off = (PARENT_BRANCH in on_the_remote(swept), list(swept.forge.deleted))
    setting(on=True)
    sweep()

    assert while_off == (True, [])
    assert PARENT_BRANCH not in on_the_remote(swept)
