"""What a unit's graph nodes read of a pull request comes from the snapshot, not the host.

The two reads a node makes through the runner's wiring are "is my pull request merged" and
"has my parent's merged". Each is answered from the snapshot the poll wrote (spec: snapshots);
the host is made unreachable here, so a read of it would fail the test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import forges
from agent_build_kit.forges import PullRequest
from agent_build_kit.pipeline import snapshots
from agent_build_kit.pipeline.pr_poller import PrState, snapshot, state_path
from agent_build_kit.pipeline.snapshots import Request
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED, branch_name
from agent_build_kit.pipeline.wiring import build_forge_state, build_fresh_base
from tests import fake_clock
from tests.conftest import make_installation
from tests.factories import stored_unit, unit

UNIT = unit("feature/1", change="feature", repo="app")


@pytest.fixture
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    fake_clock.install(monkeypatch)

    def unreachable(*args: object, **kwargs: object) -> None:
        pytest.fail("a node asked for the code host")

    monkeypatch.setattr(forges, "for_repo", unreachable)
    return make_installation(tmp_path / "planning").state_dir


def pull(number: int, state: str, branch: str) -> PullRequest:
    return PullRequest(number=number, head=branch, base="main", state=state)


def collected(state_dir: Path, repo: str, *pulls: PullRequest) -> None:
    PrState.save(state_path(state_dir, repo), {str(p.number): snapshot(p) for p in pulls}, repo)


def test_the_state_of_a_units_pull_request_is_the_snapshots(state_dir: Path) -> None:
    collected(state_dir, "app", pull(7, MERGED, branch_name(UNIT)))

    assert build_forge_state()(UNIT, 7) == MERGED


def test_a_pull_request_the_snapshot_lacks_raises_and_asks_the_round_for_it(
    state_dir: Path,
) -> None:
    with pytest.raises(LookupError, match="PR #7"):
        build_forge_state()(UNIT, 7)

    assert snapshots.requested(state_dir) == [Request(kind="pr", key="app")]


def test_a_parent_the_snapshot_shows_merged_is_recorded(tmp_path: Path, state_dir: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    parent = stored_unit("feature/1")
    child = stored_unit("feature/2", depends_on=("feature/1",), groups=(2,))
    store.upsert([parent, child])
    store.set_state(parent.id, IN_REVIEW, pr=5, branch=branch_name(parent))
    branch = branch_name(unit("feature/1"))
    collected(state_dir, "app", pull(5, MERGED, branch))
    merged: list[tuple[str, int]] = []

    def record_merge(repo: str, number: int) -> None:
        merged.append((repo, number))
        store.set_state("feature/1", MERGED)  # what the handler does

    fresh_base = build_fresh_base(store, record_merge=record_merge)
    fresh_base(unit("feature/2", depends_on=("feature/1",)), branch)

    assert merged == [("app", 5)]
