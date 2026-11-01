"""The forge reads `open_pr` makes of a unit's recorded pull request.

A host lists pull requests by head prefix, so the listing for `spec/feature/1` also holds
those of `spec/feature/10`: the pull request is found by its number among them.
"""

from __future__ import annotations

import pytest

from agent_build_kit.forges import PullRequest
from agent_build_kit.pipeline.wiring import build_forge_state, build_merge_commit
from tests.factories import unit
from tests.forges.stand_in import StandInForge, lookup

UNIT = unit("feature/1", change="feature")


def pull(number: int, state: str, branch: str = "spec/feature/1") -> PullRequest:
    return PullRequest(number=number, head=branch, base="main", state=state)


@pytest.mark.parametrize("state", ["open", "merged", "closed"])
def test_the_state_is_the_forges_for_the_units_pull_request(state: str) -> None:
    forge = StandInForge(prs=[pull(7, state)])

    assert build_forge_state(for_repo=lookup(forge))(UNIT, 7) == state


def test_a_pull_request_of_a_branch_sharing_the_prefix_is_not_taken_for_the_units() -> None:
    forge = StandInForge(prs=[pull(70, "merged", "spec/feature/10"), pull(7, "open")])

    assert build_forge_state(for_repo=lookup(forge))(UNIT, 7) == "open"


def test_a_number_the_forge_does_not_list_raises_even_when_a_neighbour_is_listed() -> None:
    forge = StandInForge(prs=[pull(70, "merged", "spec/feature/10")])

    with pytest.raises(LookupError, match="PR #7"):
        build_forge_state(for_repo=lookup(forge))(UNIT, 7)


def test_the_merge_commit_is_the_forges() -> None:
    forge = StandInForge()
    forge.merged[7] = "9f2c1ab"

    assert build_merge_commit(for_repo=lookup(forge))(UNIT, 7) == "9f2c1ab"
