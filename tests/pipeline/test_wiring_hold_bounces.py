"""The upstream guard's note says `held repeatedly by <parent>` once the count makes it so.

Read from the count the store keeps; the guard writes nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import PLANNED, RUNNING, UnitState
from agent_build_kit.pipeline.wiring import build_upstream_incomplete
from tests import fake_clock
from tests.bounce_support import bounce_times
from tests.factories import stored_unit as unit

PLAIN = "a/1 is planned — it went back after this unit started"
LIMIT = 3


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> fake_clock.FakeClock:
    return fake_clock.install(monkeypatch)


def held_by_parent(
    tmp_path: Path, clock: fake_clock.FakeClock, cause: Cause, times: int
) -> UnitStore:
    """`a/2` running, put back `times` times with `cause`, on a planned `a/1`."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("a/1", change="a"), unit("a/2", change="a", depends_on=("a/1",))])
    store.set_state("a/1", PLANNED)
    bounce_times(store, "a/2", cause, clock, times)
    store.set_state("a/2", RUNNING, branch="spec/a/2")
    return store


def note(store: UnitStore, **kw) -> str:
    found = build_upstream_incomplete(store, **kw)(store.get("a/2"))
    assert found is not None
    assert found[0] is Cause.UPSTREAM_WENT_BACK
    return found[1]


@pytest.mark.parametrize("times", [2, 3, 5])
def test_the_note_ends_held_repeatedly_once_the_next_hold_reaches_the_limit(
    tmp_path: Path, clock: fake_clock.FakeClock, times: int
) -> None:
    store = held_by_parent(tmp_path, clock, Cause.UPSTREAM_WENT_BACK, times)

    assert note(store, bounce_limit=LIMIT).endswith("held repeatedly by a/1")


def test_the_note_is_unchanged_below_the_limit_for_another_cause_and_without_a_limit(
    tmp_path: Path, clock: fake_clock.FakeClock
) -> None:
    for times in (0, 1):
        store = held_by_parent(tmp_path / f"below{times}", clock, Cause.UPSTREAM_WENT_BACK, times)
        assert note(store, bounce_limit=LIMIT) == PLAIN
    other = held_by_parent(tmp_path / "other", clock, Cause.BASE_CHANGED, 2)
    assert note(other, bounce_limit=LIMIT) == PLAIN
    over = held_by_parent(tmp_path / "over", clock, Cause.UPSTREAM_WENT_BACK, 2)
    assert note(over) == PLAIN
    # The same store, with the limit passed, is the one that changes.
    assert note(over, bounce_limit=LIMIT) != PLAIN


def test_the_guard_writes_nothing_to_the_store(tmp_path: Path, clock: fake_clock.FakeClock) -> None:
    store = held_by_parent(tmp_path, clock, Cause.UPSTREAM_WENT_BACK, 2)
    before = store.path.read_bytes()

    assert note(store, bounce_limit=LIMIT).endswith("held repeatedly by a/1")

    assert store.path.read_bytes() == before


def test_an_unplanned_parent_is_still_no_hold_at_the_limit(
    tmp_path: Path, clock: fake_clock.FakeClock
) -> None:
    store = held_by_parent(tmp_path, clock, Cause.UPSTREAM_WENT_BACK, 2)
    assert note(store, bounce_limit=LIMIT).endswith("held repeatedly by a/1")
    store.set_state("a/1", UnitState.UNPLANNED)

    assert build_upstream_incomplete(store, bounce_limit=LIMIT)(store.get("a/2")) is None
