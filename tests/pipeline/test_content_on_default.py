"""Work already on the default branch is recognised (spec: landed-carry).

Real git in temporary repositories: an origin, a clone, a parent branch holding the unit's merge
commit, and a default branch that receives the same change by a squash or a different one."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.landing_check import content_on_default
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import HELD, MERGED, SETTLING, UnitState
from tests.factories import commit_files, git, init_repo, stored_unit

PARENT = "feature/1"
CHILD = "feature/2"
BASE = {"a.txt": "one\n", "b.txt": "one\n"}
CHILD_CHANGE = {"a.txt": "two\n", "b.txt": "two\n"}


class Repos:
    """An origin and a clone with `main`, and a parent branch carrying the unit's merge."""

    def __init__(self, root: Path) -> None:
        origin = root / "origin.git"
        origin.mkdir(parents=True)
        git(origin, "init", "-q", "--bare", "-b", "main")
        self.clone = init_repo(root / "clone")
        git(self.clone, "remote", "add", "origin", str(origin))
        commit_files(self.clone, "base", BASE)
        git(self.clone, "push", "-q", "origin", "main")
        git(self.clone, "checkout", "-q", "-b", f"spec/{PARENT}")
        commit_files(self.clone, "parent", {"p.txt": "parent\n"})
        git(self.clone, "push", "-q", "origin", f"spec/{PARENT}")
        git(self.clone, "checkout", "-q", "main")

    def merge_child_into_parent(self, *, as_merge_commit: bool = False) -> str:
        """The unit's change lands on the parent's branch; the sha it records as its merge."""
        git(self.clone, "checkout", "-q", f"spec/{PARENT}")
        if as_merge_commit:
            git(self.clone, "checkout", "-q", "-b", "child")
            commit_files(self.clone, "child", CHILD_CHANGE)
            git(self.clone, "checkout", "-q", f"spec/{PARENT}")
            git(self.clone, "merge", "-q", "--no-ff", "-m", "merge child", "child")
        else:
            commit_files(self.clone, "child", CHILD_CHANGE)
        git(self.clone, "push", "-q", "origin", f"spec/{PARENT}")
        sha = git(self.clone, "rev-parse", "HEAD")
        git(self.clone, "checkout", "-q", "main")
        return sha

    def land_on_main(self, files: dict[str, str]) -> str:
        """A commit on the default branch with other history than the unit's, as a squash
        leaves it; the origin's head after it."""
        git(self.clone, "checkout", "-q", "main")
        commit_files(self.clone, "squash", files)
        git(self.clone, "push", "-q", "origin", "main")
        return git(self.clone, "rev-parse", "HEAD")


@pytest.fixture
def repos(tmp_path: Path) -> Repos:
    return Repos(tmp_path)


def test_a_change_present_through_a_squash_commit_is_recognised(repos: Repos) -> None:
    merge_sha = repos.merge_child_into_parent()
    repos.land_on_main(CHILD_CHANGE)

    assert content_on_default(repos.clone, merge_sha, "main")


def test_a_change_only_partly_present_is_not_recognised(repos: Repos) -> None:
    merge_sha = repos.merge_child_into_parent()
    repos.land_on_main({"a.txt": "two\n"})

    assert not content_on_default(repos.clone, merge_sha, "main")


def test_a_different_change_to_the_same_file_is_not_taken_for_present(repos: Repos) -> None:
    merge_sha = repos.merge_child_into_parent()
    repos.land_on_main({"a.txt": "three\n", "b.txt": "three\n"})

    assert not content_on_default(repos.clone, merge_sha, "main")


def test_a_change_not_on_the_default_branch_is_not_recognised(repos: Repos) -> None:
    merge_sha = repos.merge_child_into_parent()

    assert not content_on_default(repos.clone, merge_sha, "main")


def test_a_merge_commit_is_compared_with_its_first_parent(repos: Repos) -> None:
    merge_sha = repos.merge_child_into_parent(as_merge_commit=True)
    repos.land_on_main(CHILD_CHANGE)

    assert content_on_default(repos.clone, merge_sha, "main")


def recheck(repos: Repos, store: UnitStore) -> list[str]:
    return events.recheck_landings(
        store,
        repos={"app": repos.clone},
        merge_record=lambda unit: (unit.merge_sha, None),
        log=lambda _line: None,
    )


def unit_store(tmp_path: Path, merge_sha: str, state: UnitState, cause: Cause | None) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            stored_unit(PARENT, change="feature"),
            stored_unit(CHILD, change="feature", depends_on=(PARENT,)),
        ]
    )
    store.set_state(PARENT, MERGED, pr=1, branch=f"spec/{PARENT}")
    store.set_state(CHILD, state, pr=2, branch=f"spec/{CHILD}", cause=cause)
    store.set_merge_record(CHILD, merge_sha, None)
    if state == SETTLING:
        store.set_settling_behind(CHILD, f"spec/{PARENT}")
    return store


WAITING = [(SETTLING, None), (HELD, Cause.LANDED_OFF_DEFAULT)]


@pytest.mark.parametrize(("state", "cause"), WAITING, ids=["settling", "held"])
def test_a_waiting_unit_whose_work_is_on_the_default_branch_is_merged_with_its_head(
    tmp_path: Path, repos: Repos, state: UnitState, cause: Cause | None
) -> None:
    merge_sha = repos.merge_child_into_parent()
    store = unit_store(tmp_path, merge_sha, state, cause)
    head = repos.land_on_main(CHILD_CHANGE)

    recorded = recheck(repos, store)

    unit = store.get(CHILD)
    assert recorded == [CHILD]
    assert (unit.state, unit.merge_sha) == (MERGED, head)


@pytest.mark.parametrize(("state", "cause"), WAITING, ids=["settling", "held"])
def test_a_waiting_unit_whose_work_is_partly_on_the_default_branch_is_merged_only_once_all_is(
    tmp_path: Path, repos: Repos, state: UnitState, cause: Cause | None
) -> None:
    merge_sha = repos.merge_child_into_parent()
    store = unit_store(tmp_path, merge_sha, state, cause)
    repos.land_on_main({"a.txt": "two\n"})

    partial = recheck(repos, store)
    waiting = store.get(CHILD)
    head = repos.land_on_main({"b.txt": "two\n"})
    complete = recheck(repos, store)

    unit = store.get(CHILD)
    assert (partial, waiting.state, waiting.merge_sha) == ([], state, merge_sha)
    assert complete == [CHILD]
    assert (unit.state, unit.merge_sha) == (MERGED, head)
