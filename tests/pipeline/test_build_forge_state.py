"""The reads `open_pr` makes of a unit's recorded pull request.

Its state is read from the snapshot the round keeps (`tests/graph/test_nodes_read_pr_snapshot.py`
has the host not being asked); the merge commit is still the forge's, as an act on the host.
A pull request is found by its number: a snapshot of `spec/feature/10` does not answer for 7.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.forges import PullRequest
from agent_build_kit.pipeline.pr_poller import PrState, snapshot, state_path
from agent_build_kit.pipeline.wiring import build_forge_state, build_merge_commit
from tests.conftest import make_installation
from tests.factories import unit
from tests.forges.stand_in import StandInForge, lookup

UNIT = unit("feature/1", change="feature")


def pull(number: int, state: str, branch: str = "spec/feature/1") -> PullRequest:
    return PullRequest(number=number, head=branch, base="main", state=state)


def collect(tmp_path: Path, *pulls: PullRequest) -> None:
    state_dir = make_installation(tmp_path / "planning").state_dir
    PrState.save(
        state_path(state_dir, UNIT.repo), {str(p.number): snapshot(p) for p in pulls}, UNIT.repo
    )


@pytest.mark.parametrize("state", ["open", "merged", "closed"])
def test_the_state_is_the_snapshots_for_the_units_pull_request(tmp_path: Path, state: str) -> None:
    collect(tmp_path, pull(7, state))

    assert build_forge_state()(UNIT, 7) == state


def test_a_pull_request_of_a_branch_sharing_the_prefix_is_not_taken_for_the_units(
    tmp_path: Path,
) -> None:
    collect(tmp_path, pull(70, "merged", "spec/feature/10"), pull(7, "open"))

    assert build_forge_state()(UNIT, 7) == "open"


def test_a_number_the_snapshot_does_not_hold_raises_even_when_a_neighbour_is_held(
    tmp_path: Path,
) -> None:
    collect(tmp_path, pull(70, "merged", "spec/feature/10"))

    with pytest.raises(LookupError, match="PR #7"):
        build_forge_state()(UNIT, 7)


def test_the_merge_commit_is_the_forges() -> None:
    forge = StandInForge()
    forge.merged[7] = "9f2c1ab"

    assert build_merge_commit(for_repo=lookup(forge))(UNIT, 7) == "9f2c1ab"
