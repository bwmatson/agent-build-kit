"""Work already on the default branch is recognised (spec: landed-carry).

Real git in temporary repositories (the landing world the re-check tests share): the unit's merge
commit sits on a parent branch, and the default branch receives the same change by a squash or
a different one."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.landing_check import content_on_default
from agent_build_kit.pipeline.units import SETTLING
from tests.landing_world import CHILD_CHANGE, Landing


@pytest.fixture
def landing(tmp_path: Path) -> Landing:
    return Landing(tmp_path, child_state=SETTLING, cause=None)


def test_a_change_present_through_a_squash_commit_is_recognised(landing: Landing) -> None:
    landing.land_on_main(CHILD_CHANGE)

    assert content_on_default(landing.clone, landing.child_sha, "main")


def test_a_change_only_partly_present_is_not_recognised(landing: Landing) -> None:
    landing.land_on_main({"a.txt": "two\n"})

    assert not content_on_default(landing.clone, landing.child_sha, "main")


def test_a_different_change_to_the_same_file_is_not_taken_for_present(landing: Landing) -> None:
    landing.land_on_main({"a.txt": "three\n", "b.txt": "three\n"})

    assert not content_on_default(landing.clone, landing.child_sha, "main")


def test_a_change_not_on_the_default_branch_is_not_recognised(landing: Landing) -> None:
    assert not content_on_default(landing.clone, landing.child_sha, "main")


def test_a_merge_commit_is_compared_with_its_first_parent(tmp_path: Path) -> None:
    landing = Landing(tmp_path, child_state=SETTLING, cause=None, as_merge_commit=True)
    landing.land_on_main(CHILD_CHANGE)

    assert content_on_default(landing.clone, landing.child_sha, "main")
