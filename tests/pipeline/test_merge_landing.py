"""A merge is recorded only when its commit is on the default branch (spec: merge-landing).

Real git in temporary repositories: an origin, a clone the dispatch checks against, a parent
branch and a child merged into one or the other. The forge is not asked: the commit comes from
the listing's snapshot."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.forges.base import PullRequest
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.landing_check import merged_on_default
from agent_build_kit.pipeline.loaded_code import LoadedCode
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, MERGED, SETTLING, waiting_on
from tests.conftest import make_installation
from tests.factories import commit, git, init_repo, stored_unit

PARENT = "feature/1"
CHILD = "feature/2"
DEPENDENT = "feature/3"
PR = 2


class Repos:
    """An origin and a clone with `main`, and a parent branch pushed beside it."""

    def __init__(self, root: Path, clone: Path | None = None) -> None:
        self.origin = root / "origin.git"
        self.origin.mkdir(parents=True)
        git(self.origin, "init", "-q", "--bare", "-b", "main")
        self.clone = init_repo(clone or root / "clone")
        git(self.clone, "remote", "add", "origin", str(self.origin))
        commit(self.clone, "base")
        git(self.clone, "push", "-q", "origin", "main")
        git(self.clone, "checkout", "-q", "-b", f"spec/{PARENT}")
        self.parent_tip = commit(self.clone, "parent")
        git(self.clone, "push", "-q", "origin", f"spec/{PARENT}")
        git(self.clone, "checkout", "-q", "main")

    def land_on_main(self) -> str:
        """A commit on the default branch of the origin, as a merge into it leaves."""
        git(self.clone, "checkout", "-q", "main")
        sha = commit(self.clone, "merged-into-main")
        git(self.clone, "push", "-q", "origin", "main")
        return sha

    def land_on_parent(self) -> str:
        """A commit on the parent's branch only, as a merge into the parent's branch leaves."""
        git(self.clone, "checkout", "-q", f"spec/{PARENT}")
        sha = commit(self.clone, "merged-into-parent")
        git(self.clone, "push", "-q", "origin", f"spec/{PARENT}")
        git(self.clone, "checkout", "-q", "main")
        return sha


class World:
    def __init__(
        self, tmp_path: Path, *, parent_state, resume=None, production: bool = False
    ) -> None:
        inst = make_installation(tmp_path / "inst")
        self.repos = Repos(tmp_path / "git", clone=inst.checkouts["app"])
        self.store = UnitStore(tmp_path / "units.json")
        self.store.upsert(
            [
                stored_unit(PARENT, change="feature"),
                stored_unit(CHILD, change="feature", depends_on=(PARENT,)),
                stored_unit(DEPENDENT, change="feature", depends_on=(CHILD,), merge_needs=(CHILD,)),
            ]
        )
        self.store.set_state(PARENT, parent_state, pr=1, branch=f"spec/{PARENT}")
        self.store.set_state(CHILD, IN_REVIEW, pr=PR, branch=f"spec/{CHILD}")
        self.log: list[str] = []
        if production:
            self.dispatch = cli.dispatch_for(inst, self.store)
        else:
            self.dispatch = events.build_dispatch(
                self.store,
                restack=lambda **k: None,
                merge_record=lambda unit: (unit.merge_sha, None),
                repos={"app": self.repos.clone},
                **({"resume": resume} if resume else {}),
                log=self.log.append,
            )

    def merged_into(self, base: str, sha: str | None):
        pull = PullRequest(
            number=PR, head=f"spec/{CHILD}", base=base, state="merged", merge_commit=sha
        )
        return self.dispatch("merged", PR, repo="app", pull=pull)

    def waiting(self) -> list[str]:
        loaded = LoadedCode(
            number=9,
            kit_repo="app",
            kit_root=str(self.repos.clone),
            kit_head=git(self.repos.clone, "rev-parse", "main"),
        )
        units = self.store.all()
        dependent = self.store.get(DEPENDENT)
        return [u.id for u in waiting_on(dependent, units, loaded)]


@pytest.fixture
def merged_parent(tmp_path: Path) -> World:
    return World(tmp_path, parent_state=MERGED)


@pytest.fixture
def open_parent(tmp_path: Path) -> World:
    return World(tmp_path, parent_state=IN_REVIEW)


def test_a_commit_on_the_default_branch_is_merged_on_default(tmp_path: Path) -> None:
    repos = Repos(tmp_path)

    assert merged_on_default(repos.clone, repos.land_on_main(), "main")


def test_a_commit_only_on_another_branch_is_not_merged_on_default(tmp_path: Path) -> None:
    repos = Repos(tmp_path)

    assert not merged_on_default(repos.clone, repos.land_on_parent(), "main")


def test_a_commit_the_clone_only_fetches_is_merged_on_default(tmp_path: Path) -> None:
    """The check fetches: a merge another clone pushed is seen without a manual fetch."""
    repos = Repos(tmp_path)
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(repos.origin), str(other))
    git(other, "config", "user.email", "t@t.t")
    git(other, "config", "user.name", "t")
    sha = commit(other, "elsewhere")
    git(other, "push", "-q", "origin", "main")

    assert merged_on_default(repos.clone, sha, "main")


def test_a_merge_whose_commit_is_not_on_the_default_branch_is_not_recorded_merged(
    merged_parent: World,
) -> None:
    sha = merged_parent.repos.land_on_parent()

    merged_parent.merged_into("main", sha)
    merged_parent.dispatch("settled", PR, repo="app")

    unit = merged_parent.store.get(CHILD)
    assert unit.state != MERGED
    assert unit.merge_sha is None


def test_a_merge_into_a_merged_units_branch_holds_the_unit_landed_off_default(
    merged_parent: World,
) -> None:
    sha = merged_parent.repos.land_on_parent()

    merged_parent.merged_into(f"spec/{PARENT}", sha)

    unit = merged_parent.store.get(CHILD)
    assert (unit.state, unit.cause) == (HELD, Cause.LANDED_OFF_DEFAULT)
    assert unit.merge_sha is None
    for named in (f"#{PR}", f"spec/{PARENT}", "main"):
        assert named in unit.note


def test_a_held_landed_off_default_unit_is_not_settled_into_merged(merged_parent: World) -> None:
    sha = merged_parent.repos.land_on_parent()
    merged_parent.merged_into(f"spec/{PARENT}", sha)

    merged_parent.dispatch("settled", PR, repo="app")

    unit = merged_parent.store.get(CHILD)
    assert (unit.state, unit.merge_sha) == (HELD, None)


def test_a_merge_into_an_open_units_branch_leaves_the_unit_settling_with_a_note(
    open_parent: World,
) -> None:
    sha = open_parent.repos.land_on_parent()

    open_parent.merged_into(f"spec/{PARENT}", sha)

    unit = open_parent.store.get(CHILD)
    assert unit.state == SETTLING
    assert unit.cause != Cause.LANDED_OFF_DEFAULT
    assert "lands when" in unit.note
    assert PARENT in unit.note


def test_a_unit_whose_listing_has_no_commit_stays_settling_until_a_report_carries_one(
    merged_parent: World,
) -> None:
    merged_parent.merged_into(f"spec/{PARENT}", None)
    unit = merged_parent.store.get(CHILD)
    assert (unit.state, unit.merge_sha) == (SETTLING, None)

    merged_parent.merged_into(f"spec/{PARENT}", merged_parent.repos.land_on_parent())

    assert merged_parent.store.get(CHILD).state == HELD


def test_the_dependents_of_a_held_unit_keep_waiting_for_it(merged_parent: World) -> None:
    sha = merged_parent.repos.land_on_parent()
    merged_parent.merged_into(f"spec/{PARENT}", sha)

    assert merged_parent.store.get(CHILD).state == HELD
    assert merged_parent.waiting() == [CHILD]


def test_the_production_dispatch_holds_a_merge_into_a_merged_units_branch(
    tmp_path: Path,
) -> None:
    world = World(tmp_path, parent_state=MERGED, production=True)

    world.merged_into(f"spec/{PARENT}", world.repos.land_on_parent())

    unit = world.store.get(CHILD)
    assert (unit.state, unit.cause) == (HELD, Cause.LANDED_OFF_DEFAULT)


def test_a_merge_into_a_merged_units_branch_reaches_the_unit_thread_as_a_hold(
    tmp_path: Path,
) -> None:
    delivered: list[str] = []

    def resume(unit, kind, *rest) -> bool:
        delivered.append(kind)
        return True

    world = World(tmp_path, parent_state=MERGED, resume=resume)

    world.merged_into(f"spec/{PARENT}", world.repos.land_on_parent())

    assert delivered == ["hold"]
    assert world.store.get(CHILD).cause == Cause.LANDED_OFF_DEFAULT


def test_a_unit_merged_into_an_open_units_branch_stays_settling_when_its_checks_complete(
    open_parent: World,
) -> None:
    open_parent.merged_into(f"spec/{PARENT}", open_parent.repos.land_on_parent())

    open_parent.dispatch("settled", PR, repo="app")

    unit = open_parent.store.get(CHILD)
    assert unit.state == SETTLING
    assert "lands when" in unit.note
    assert CHILD in open_parent.waiting()
