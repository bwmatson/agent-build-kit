"""A unit with a late fix lists two pull requests and merges on the second (spec:
merged-waits-for-ci). It keeps its id, `pr` and `branch` name the second, and the second is titled
`<unit>: late fix for #<n>`."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.unit_store import Pull, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED, PLANNED, SETTLING
from agent_build_kit.pipeline.wiring import build_open_pr
from tests.factories import stored_unit
from tests.sized_forge import REPO, SizedForge

FIX_BRANCH = "spec/add-marker/1-fix1"
FIRST_SHA = "abc123"
SECOND_SHA = "def456"
TICK = 12
MERGED_AT = datetime(2026, 10, 27, 11, 43, tzinfo=UTC)


class Forge(SizedForge):
    def __init__(self) -> None:
        super().__init__(10)
        self.created: list[tuple[str, str]] = []

    def create_pr(self, repo, *, head, base, title, body) -> int:  # type: ignore[bad-override]
        self.created.append((head, title))
        return 9


@pytest.fixture
def store(tmp_path: Path) -> UnitStore:
    """The unit is on its late fix: `planned` on the fix branch, the first pull request merged."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("add-marker/1")])
    store.set_state("add-marker/1", PLANNED, branch=FIX_BRANCH)
    store.set_pulls(
        "add-marker/1",
        (Pull(number=4, branch="spec/add-marker/1", merged_at=MERGED_AT, merge_sha=FIRST_SHA),),
    )
    return store


def open_late_fix(store: UnitStore, tmp_path: Path, forge: Forge) -> None:
    open_pr = build_open_pr(for_repo=lambda repo: (forge, REPO), store=store)
    open_pr(store.get("add-marker/1"), body="b", base="main", cwd=tmp_path)
    store.set_state("add-marker/1", IN_REVIEW, pr=9, branch=FIX_BRANCH)


def merge_second(store: UnitStore) -> None:
    events.on_merged(
        9,
        repo="app",
        store=store,
        restack=lambda **k: None,
        merge_record=lambda unit: (SECOND_SHA, TICK),
        log=lambda m: None,
    )


def test_the_late_fix_pull_request_is_titled_for_the_first_and_listed_beside_it(
    store: UnitStore, tmp_path: Path
) -> None:
    forge = Forge()

    open_late_fix(store, tmp_path, forge)

    assert forge.created == [(FIX_BRANCH, "add-marker/1: late fix for #4")]
    unit = store.get("add-marker/1")
    assert unit.id == "add-marker/1"
    assert [(p.number, p.role, p.branch) for p in unit.pulls] == [
        (4, "original", "spec/add-marker/1"),
        (9, "late-fix", FIX_BRANCH),
    ]
    assert unit.pulls[1].opened_at is not None
    assert (unit.pr, unit.branch) == (9, FIX_BRANCH)


def test_the_second_merge_is_recorded_and_the_unit_settles_again(
    store: UnitStore, tmp_path: Path
) -> None:
    open_late_fix(store, tmp_path, Forge())

    merge_second(store)

    unit = store.get("add-marker/1")
    assert unit.state == SETTLING
    assert unit.merge_sha == SECOND_SHA
    assert unit.merged_tick is None
    assert [p.number for p in unit.pulls] == [4, 9]
    assert unit.pulls[0].merge_sha == FIRST_SHA
    assert unit.pulls[1].merge_sha == SECOND_SHA
    assert unit.pulls[1].merged_at is not None


def test_clean_checks_on_the_second_pull_request_make_the_unit_merged(
    store: UnitStore, tmp_path: Path
) -> None:
    open_late_fix(store, tmp_path, Forge())
    merge_second(store)
    dispatch = events.build_dispatch(
        store,
        restack=lambda **k: None,
        merge_record=lambda unit: (SECOND_SHA, TICK),
        log=lambda m: None,
    )

    assert dispatch("settled", 9, repo="app") is True

    unit = store.get("add-marker/1")
    assert unit.state == MERGED
    assert unit.merged_tick == TICK
    assert unit.merge_sha == SECOND_SHA
