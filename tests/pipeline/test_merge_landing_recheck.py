"""A unit that landed later is recognised each round (spec: merge-landing).

Real git in temporary repositories: an origin, a clone, a parent branch and a child whose merge
commit sits on the parent's branch until the parent's work reaches the default branch."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import HELD, MERGED, SETTLING, UnitState
from tests.factories import commit, git, init_repo, stored_unit

PARENT = "feature/1"
CHILD = "feature/2"


class Landing:
    """An origin and a clone, a parent branch with the child's merge commit on it, and a store
    holding the child in the state under test."""

    def __init__(self, root: Path, *, child_state: UnitState, cause: Cause | None) -> None:
        origin = root / "origin.git"
        origin.mkdir(parents=True)
        git(origin, "init", "-q", "--bare", "-b", "main")
        self.clone = init_repo(root / "clone")
        git(self.clone, "remote", "add", "origin", str(origin))
        commit(self.clone, "base")
        git(self.clone, "push", "-q", "origin", "main")
        git(self.clone, "checkout", "-q", "-b", f"spec/{PARENT}")
        self.child_sha = commit(self.clone, "child-merged-into-parent")
        git(self.clone, "push", "-q", "origin", f"spec/{PARENT}")
        git(self.clone, "checkout", "-q", "main")
        self.store = UnitStore(root / "units.json")
        self.store.upsert(
            [
                stored_unit(PARENT, change="feature"),
                stored_unit(CHILD, change="feature", depends_on=(PARENT,)),
            ]
        )
        self.store.set_state(PARENT, MERGED, pr=1, branch=f"spec/{PARENT}")
        self.store.set_state(CHILD, child_state, pr=2, branch=f"spec/{CHILD}", cause=cause)
        self.store.set_merge_record(CHILD, self.child_sha, None)
        if child_state == SETTLING:
            self.store.set_settling_behind(CHILD, f"spec/{PARENT}")
        self.resumed: list[tuple[str, str]] = []

    def carry_parent_to_main(self) -> None:
        """The parent's branch merged into the default branch, as a carry or a person's merge
        leaves it: the child's commit is then an ancestor of `main`."""
        git(self.clone, "checkout", "-q", "main")
        git(self.clone, "merge", "-q", "--no-ff", "-m", "carry", f"spec/{PARENT}")
        git(self.clone, "push", "-q", "origin", "main")

    def resume(self, unit: StoredUnit, kind: str, reason: str, feedback: str) -> bool:
        self.resumed.append((unit.id, kind))
        return True

    def recheck(self) -> list[str]:
        return events.recheck_landings(
            self.store,
            repos={"app": self.clone},
            merge_record=lambda unit: (unit.merge_sha, None),
            resume=self.resume,
            log=lambda _line: None,
        )


SETTLING_BEHIND_PARENT = (SETTLING, None)
HELD_OFF_DEFAULT = (HELD, Cause.LANDED_OFF_DEFAULT)


@pytest.fixture(params=[SETTLING_BEHIND_PARENT, HELD_OFF_DEFAULT], ids=["settling", "held"])
def waiting_child(request, tmp_path: Path) -> Landing:
    state, cause = request.param
    return Landing(tmp_path, child_state=state, cause=cause)


def test_a_waiting_unit_becomes_merged_with_its_commit_once_the_commit_is_on_the_default_branch(
    waiting_child: Landing,
) -> None:
    waiting_child.carry_parent_to_main()

    recorded = waiting_child.recheck()

    unit = waiting_child.store.get(CHILD)
    assert recorded == [CHILD]
    assert (unit.state, unit.merge_sha) == (MERGED, waiting_child.child_sha)


def test_a_waiting_unit_whose_commit_is_not_on_the_default_branch_is_left_as_it_is(
    waiting_child: Landing,
) -> None:
    before = waiting_child.store.get(CHILD)

    recorded = waiting_child.recheck()

    unit = waiting_child.store.get(CHILD)
    assert recorded == []
    assert (unit.state, unit.cause, unit.merge_sha) == (
        before.state,
        before.cause,
        before.merge_sha,
    )


def test_a_settling_unit_that_merged_into_the_default_branch_is_left_to_its_checks(
    tmp_path: Path,
) -> None:
    landing = Landing(tmp_path, child_state=SETTLING, cause=None)
    landing.store.set_settling_behind(CHILD, "")
    landing.carry_parent_to_main()

    recorded = landing.recheck()

    assert recorded == []
    assert landing.store.get(CHILD).state == SETTLING


def test_a_held_unit_that_landed_later_has_its_thread_sent_merged(tmp_path: Path) -> None:
    landing = Landing(tmp_path, child_state=HELD, cause=Cause.LANDED_OFF_DEFAULT)
    landing.carry_parent_to_main()

    landing.recheck()

    assert landing.resumed == [(CHILD, "merged")]
