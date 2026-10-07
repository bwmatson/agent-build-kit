"""A unit that turns out not to be needed leaves the stack as a merged one does.

What is stacked on it is moved onto the base `base_of` now gives it, and its
pull request retargeted, before the satisfied unit's own pull request is
closed. The tests run the real restack against real git repositories and a
bare remote, with the stand-in forge as the code host.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_build_kit import forges
from agent_build_kit.forges.base import PullRequest
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.restack import move_branch_onto
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED, PLANNED, SATISFIED, UnitState, base_of
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.factories import git, init_repo
from tests.factories import stored_unit as unit
from tests.forges.stand_in import StandInForge, lookup


class RecordingForge(StandInForge):
    """Notes each retarget in a log shared with the test, and can refuse one."""

    def __init__(self, order: list[str], *, refuses: int | None = None) -> None:
        super().__init__()
        self.order = order
        self.refuses = refuses
        self.bases: dict[int, tuple[str, str]] = {}

    def list_prs(self, repo, *, head_prefix: str = "") -> list[PullRequest]:
        return [
            PullRequest(number=number, head=head, base=base, state=IN_REVIEW)
            for number, (head, base) in self.bases.items()
            if head.startswith(head_prefix)
        ]

    def update_pr(self, repo, pr: int, *, base: str = "", body: str = "") -> None:
        if pr == self.refuses:
            raise RuntimeError(f"host refused to retarget #{pr}")
        self.order.append(f"retarget #{pr}")
        head, _ = self.bases[pr]
        self.bases[pr] = (head, base)
        super().update_pr(repo, pr, base=base, body=body)

    def retargeted(self) -> list[tuple[int, str]]:
        return [(u["pr"], u["base"]) for u in self.updated]


class World:
    """A code repo with a bare remote, the unit store, and the host."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.order: list[str] = []
        self.forge = RecordingForge(self.order)
        monkeypatch.setattr(forges, "for_repo", lookup(self.forge))
        self.remote = tmp_path / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(self.remote)], check=True)
        self.repo = init_repo(tmp_path / "app")
        git(self.repo, "remote", "add", "origin", str(self.remote))
        self.commit("base.txt")
        git(self.repo, "push", "-q", "-u", "origin", "main")
        self.store = UnitStore(tmp_path / "units.json")
        self.locks = tmp_path / "locks"
        self.trees = tmp_path / "trees"

    def commit(self, name: str, content: str = "x") -> None:
        (self.repo / name).write_text(content)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", f"add {name}")

    def branch(self, name: str, onto: str, *, file: str | None = None) -> None:
        """A branch on `onto`, with one commit of its own when `file` is given,
        published to the remote."""
        git(self.repo, "checkout", "-q", "-b", name, onto)
        if file:
            self.commit(file)
        git(self.repo, "push", "-q", "origin", name)
        git(self.repo, "checkout", "-q", "main")

    def merge(self, branch: str) -> None:
        git(self.repo, "merge", "-q", "--no-ff", "-m", f"merge {branch}", branch)
        git(self.repo, "push", "-q", "origin", "main")

    def sha(self, ref: str) -> str:
        return git(self.repo, "rev-parse", ref)

    def own_commits(self, branch: str, base: str) -> list[str]:
        return git(self.repo, "log", "--format=%s", f"{base}..{branch}").splitlines()

    def add(
        self, uid: str, state: UnitState, *depends_on: str, pr: int | None = None, **extra
    ) -> None:
        self.store.upsert([unit(uid, depends_on=depends_on, **extra)])
        branch = f"spec/{uid}"
        self.store.set_state(uid, state, pr=pr, branch=branch if state != SATISFIED else None)
        if pr:
            self.forge.bases[pr] = (branch, f"spec/{depends_on[0]}" if depends_on else "main")
        if pr and state == IN_REVIEW:
            # Approved and pushed, as a unit waiting in review is.
            head = self.sha(branch)
            self.store.record_approval(uid, head)
            self.store.record_push(uid, head)

    def restack(self, *, conflicts_stop: bool = False):
        kwargs: dict = {}
        if conflicts_stop:
            # The real conflict, with no agent to resolve it.
            kwargs["move"] = lambda repo, branch, *, new_base, old_base, **k: move_branch_onto(
                repo, branch, new_base=new_base, old_base=old_base
            )
        return events.build_restack(
            repos={"app": self.repo},
            store=self.store,
            root=self.trees,
            tier1=lambda **k: (True, ""),
            comment=lambda *a, **k: None,
            **kwargs,
        )

    def release(self, uid: str = "feature/2", **overrides) -> list[str]:
        """Release the unit's dependents; returns the log lines and what could
        not be moved."""
        lines: list[str] = []
        kwargs: dict = {
            "restack": self.restack(),
            "claim": events.build_claim(self.locks),
            "retarget": events.build_retarget(),
            "settled": events.build_settled({"app": self.repo}),
            "log": lines.append,
        }
        self.unmoved = events.release_children(
            self.store.get(uid), store=self.store, **{**kwargs, **overrides}
        )
        return lines

    def remove(self, uid: str = "feature/2") -> list[str]:
        """What the tick does once the run that found the unit satisfied has
        left its tree."""
        lines: list[str] = []
        events.remove_satisfied(
            self.store.get(uid),
            store=self.store,
            claim=events.build_claim(self.locks),
            remove_worktree=lambda repo, branch: self.order.append("worktree"),
            delete_branch=lambda repo, branch: self.order.append("branch"),
            on_new_base=lambda child: events.pr_based_on(child, base_of(child, self.store.all())),
            log=lines.append,
        )
        return lines


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    return World(tmp_path, monkeypatch)


@pytest.fixture
def after_merge(world: World) -> World:
    """`feature/1` merged, `feature/2` satisfied on it, `feature/3` in review on
    `feature/2`'s branch."""
    world.branch("spec/feature/1", "main", file="one.txt")
    world.merge("spec/feature/1")
    world.branch("spec/feature/2", "spec/feature/1")
    world.branch("spec/feature/3", "spec/feature/2", file="three.txt")
    world.add("feature/1", MERGED, pr=1)
    world.add("feature/2", SATISFIED, "feature/1", pr=2)
    world.add("feature/3", IN_REVIEW, "feature/2", pr=3)
    return world


@pytest.fixture
def before_merge(world: World) -> World:
    """`feature/1` still in review; `feature/2` satisfied on it; `feature/3` in
    review on `feature/2`'s branch."""
    world.branch("spec/feature/1", "main", file="one.txt")
    world.branch("spec/feature/2", "spec/feature/1")
    world.branch("spec/feature/3", "spec/feature/2", file="three.txt")
    # Work that landed on `feature/1` after the others were cut from it.
    git(world.repo, "checkout", "-q", "spec/feature/1")
    world.commit("more.txt")
    git(world.repo, "push", "-q", "origin", "spec/feature/1")
    git(world.repo, "checkout", "-q", "main")
    world.add("feature/1", IN_REVIEW, pr=1)
    world.add("feature/2", SATISFIED, "feature/1", pr=2)
    world.add("feature/3", IN_REVIEW, "feature/2", pr=3)
    return world


@pytest.fixture
def cut_from_open_predecessor(world: World) -> World:
    """As `before_merge`, with no commit on `feature/1` since the others were
    cut from it: the satisfied unit added nothing, so every branch holds the
    others' tips."""
    world.branch("spec/feature/1", "main", file="one.txt")
    world.branch("spec/feature/2", "spec/feature/1")
    world.branch("spec/feature/3", "spec/feature/2", file="three.txt")
    world.add("feature/1", IN_REVIEW, pr=1)
    world.add("feature/2", SATISFIED, "feature/1", pr=2)
    world.add("feature/3", IN_REVIEW, "feature/2", pr=3)
    return world


# --- 1.1 dependents leave a satisfied unit as they leave a merged one -----------


def test_a_dependent_in_review_is_restacked_onto_the_trunk_and_retargeted(
    after_merge: World,
) -> None:
    after_merge.release()

    assert after_merge.forge.retargeted() == [(3, "main")]
    assert after_merge.own_commits("spec/feature/3", "origin/main") == ["add three.txt"]
    assert after_merge.store.get("feature/2").state == SATISFIED


def test_a_dependent_whose_predecessor_is_open_moves_onto_the_predecessor(
    before_merge: World,
) -> None:
    before_merge.release()

    assert before_merge.forge.retargeted() == [(3, "spec/feature/1")], "not to the trunk"
    assert before_merge.own_commits("spec/feature/3", "spec/feature/1") == ["add three.txt"]
    assert "add more.txt" in before_merge.own_commits("spec/feature/3", "main")


def test_a_dependent_whose_run_holds_its_branch_is_told_and_not_rebased(
    after_merge: World,
) -> None:
    told: list[tuple[str, str, str]] = []
    retargeted: list[tuple[str, str]] = []
    before = after_merge.sha("spec/feature/3")

    def resume(unit, kind, reason, feedback, **kwargs) -> bool:
        told.append((unit.id, kind, reason))
        return True

    after_merge.release(
        resume=resume, retarget=lambda child, base: retargeted.append((child.id, base))
    )

    assert told == [("feature/3", "base_moved", "main")]
    assert after_merge.sha("spec/feature/3") == before, "no rebase under the run"
    assert retargeted == [("feature/3", "main")]


def test_a_dependent_being_built_is_retargeted_and_its_branch_left(after_merge: World) -> None:
    before = after_merge.sha("spec/feature/3")
    retargeted: list[tuple[str, str]] = []

    with branch_lock("spec/feature/3", root=after_merge.locks):
        after_merge.release(retarget=lambda child, base: retargeted.append((child.id, base)))

    assert after_merge.sha("spec/feature/3") == before
    assert retargeted == [("feature/3", "main")]


def test_a_conflicting_restack_takes_the_merge_paths_conflict_handling(
    after_merge: World,
) -> None:
    """Handed to the adapt step, as on a merge: the dependent goes back to
    planned with the reason, and the satisfied unit stays satisfied."""
    git(after_merge.repo, "checkout", "-q", "main")
    after_merge.commit("three.txt", "the trunk's own three")
    git(after_merge.repo, "push", "-q", "origin", "main")
    before = after_merge.sha("spec/feature/3")

    after_merge.release(restack=after_merge.restack(conflicts_stop=True))

    child = after_merge.store.get("feature/3")
    assert child.state == PLANNED
    assert "could not be merged" in child.history[-1]["note"]
    assert after_merge.sha("spec/feature/3") == before
    assert after_merge.store.get("feature/2").state == SATISFIED


def test_a_dependent_in_another_repo_is_neither_restacked_nor_retargeted(
    after_merge: World,
) -> None:
    after_merge.store.upsert([unit("feature/9", repo="platform", depends_on=("feature/2",))])
    after_merge.store.set_state("feature/9", IN_REVIEW, pr=9, branch="spec/feature/9")
    restacked: list[str] = []
    real = after_merge.restack()

    def restack(**kwargs) -> None:
        restacked.append(kwargs["child"].id)
        real(**kwargs)

    after_merge.release(restack=restack)

    assert restacked == ["feature/3"]
    assert 9 not in [pr for pr, _ in after_merge.forge.retargeted()]


def test_releasing_twice_moves_nothing_the_second_time(after_merge: World) -> None:
    after_merge.release()
    moved = after_merge.sha("spec/feature/3")
    retargets = list(after_merge.forge.retargeted())

    after_merge.release()

    assert after_merge.sha("spec/feature/3") == moved, "no branch rebased"
    assert after_merge.forge.retargeted() == retargets, "no pull request retargeted"


def test_a_dependent_already_holding_its_new_base_is_still_retargeted(
    cut_from_open_predecessor: World,
) -> None:
    """The normal case: nothing to rebase, but the pull request is still on the
    branch that is about to close."""
    world = cut_from_open_predecessor

    world.release()

    assert world.forge.retargeted() == [(3, "spec/feature/1")]

    world.release()

    assert world.forge.retargeted() == [(3, "spec/feature/1")], "not again"


def test_releasing_twice_tells_a_dependents_thread_once(
    cut_from_open_predecessor: World,
) -> None:
    world = cut_from_open_predecessor
    told: list[str] = []

    def resume(unit, kind, reason, feedback, **kwargs) -> bool:
        told.append(unit.id)
        return True

    world.release(resume=resume)
    world.release(resume=resume)

    assert told == ["feature/3"]
    assert world.forge.retargeted() == [(3, "spec/feature/1")]


# --- 1.2 the order, the branch a dependent builds on, a failed retarget ---------


def test_the_dependents_move_then_the_pull_request_closes_then_the_branch_goes(
    after_merge: World,
) -> None:
    after_merge.release()
    after_merge.order.append("close")
    after_merge.remove()

    assert after_merge.order == ["retarget #3", "close", "worktree", "branch"]


def test_a_branch_a_dependent_still_builds_on_is_kept(after_merge: World) -> None:
    after_merge.release()
    with branch_lock("spec/feature/3", root=after_merge.locks):
        lines = after_merge.remove()

    assert "branch" not in after_merge.order
    assert any("spec/feature/2" in line and "kept" in line for line in lines)


def test_a_retarget_that_fails_leaves_the_unit_satisfied_and_moves_the_others(
    after_merge: World,
) -> None:
    after_merge.branch("spec/feature/4", "spec/feature/2", file="four.txt")
    after_merge.add("feature/4", IN_REVIEW, "feature/2", pr=4)
    after_merge.forge.refuses = 3

    lines = after_merge.release()
    after_merge.remove()

    assert after_merge.store.get("feature/2").state == SATISFIED
    assert after_merge.forge.retargeted() == [(4, "main")]
    assert len(after_merge.unmoved) == 1
    assert "feature/3" in after_merge.unmoved[0] and "host refused" in after_merge.unmoved[0]
    assert after_merge.own_commits("spec/feature/4", "origin/main") == ["add four.txt"]
    assert any("feature/3" in line and "host refused" in line for line in lines)
    assert "branch" not in after_merge.order, "feature/3 is still on it"
