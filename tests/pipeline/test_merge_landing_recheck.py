"""A unit that landed later is recognised each round (spec: merge-landing).

Real git in temporary repositories: an origin, a clone, a parent branch and a child whose merge
commit sits on the parent's branch until the parent's work reaches the default branch."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import HELD, MERGED, SETTLING
from tests.landing_world import CHILD, Landing

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


def test_a_waiting_unit_whose_work_is_on_the_default_branch_is_merged_with_its_head(
    waiting_child: Landing,
) -> None:
    head = waiting_child.land_on_main({"a.txt": "two\n", "b.txt": "two\n"})

    recorded = waiting_child.recheck()

    unit = waiting_child.store.get(CHILD)
    assert recorded == [CHILD]
    assert (unit.state, unit.merge_sha) == (MERGED, head)


def test_a_waiting_unit_whose_work_is_partly_on_the_default_branch_is_merged_only_once_all_is(
    waiting_child: Landing,
) -> None:
    before = waiting_child.store.get(CHILD)
    waiting_child.land_on_main({"a.txt": "two\n"})

    partial = waiting_child.recheck()
    waiting = waiting_child.store.get(CHILD)
    head = waiting_child.land_on_main({"b.txt": "two\n"})
    complete = waiting_child.recheck()

    unit = waiting_child.store.get(CHILD)
    assert (partial, waiting.state, waiting.merge_sha) == ([], before.state, before.merge_sha)
    assert complete == [CHILD]
    assert (unit.state, unit.merge_sha) == (MERGED, head)
