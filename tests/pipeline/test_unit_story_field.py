"""A unit remembers its Story, and the mapping survives replans and joins
(spec: tracker-mapping, "A unit remembers its Story, and the mapping survives replans and joins").
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_build_kit.pipeline.tracker_file import StoryMapping, story_mapping
from agent_build_kit.pipeline.unit_store import Cause, HeldBy, UnitStore
from agent_build_kit.pipeline.units import HELD, Member, UnitState
from tests.factories import stored_unit, unit

STORY = "story-7"


def _raw(store: UnitStore, unit_id: str) -> dict:
    records = json.loads(store.path.read_text())["units"]
    return next(record for record in records if record["id"] == unit_id)


def _held(tmp_path: Path) -> UnitStore:
    """app/3 holds groups 3 and 4 with a Story, started and held for its size."""
    store = UnitStore(tmp_path / "units.json")
    store.import_units(
        [stored_unit("app/3", change="app", groups=(3, 4), branch="spec/app/3", story=STORY)]
    )
    store.set_state("app/3", HELD, held_by=HeldBy.SIZE, cause=Cause.TOO_BIG_FOR_TIER)
    return store


def test_a_story_round_trips_and_a_unit_with_none_writes_no_key_an_older_reader_would_refuse(
    tmp_path: Path,
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.import_units(
        [stored_unit("app/1", change="app", story=STORY), stored_unit("app/2", change="app")]
    )

    assert UnitStore(store.path).get("app/1").story == STORY
    assert _raw(store, "app/1")["story"] == STORY
    # An older reader refuses an unknown key that holds a value and drops an empty one; a unit
    # with no Story writes no key at all, as a store from before the field has none.
    assert "story" not in _raw(store, "app/2")
    assert UnitStore(store.path).get("app/2").story is None


def test_a_replan_that_keeps_a_unit_keeps_its_story_and_sets_none_on_a_new_one(
    tmp_path: Path,
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.import_units([stored_unit("app/2", change="app", groups=(2,), story=STORY)])

    store.upsert(
        [unit("app/1", change="app", groups=(1,)), unit("app/2", change="app", groups=(2,))],
        change="app",
    )

    assert store.get("app/2").story == STORY
    assert store.get("app/1").story is None


def test_a_successor_with_the_same_groups_takes_the_story(tmp_path: Path) -> None:
    store = _held(tmp_path)

    store.supersede("app/3", [unit("app/3-s1", change="app", groups=(3, 4))])

    assert store.get("app/3-s1").story == STORY
    assert store.get("app/3").story is None
    assert not store.get("app/3").story_superseded


def test_a_successor_with_different_groups_leaves_the_old_story_superseded(
    tmp_path: Path,
) -> None:
    store = _held(tmp_path)

    store.supersede(
        "app/3",
        [unit("app/3-s1", change="app", groups=(3,)), unit("app/3-s2", change="app", groups=(4,))],
    )

    assert store.get("app/3-s1").story is None
    assert store.get("app/3-s2").story is None
    old = store.get("app/3")
    assert old.state == UnitState.CLOSED
    assert old.story == STORY and old.story_superseded


def test_a_joined_unit_has_its_own_features_story_and_relates_the_others() -> None:
    joined = unit("y/4", change="y", groups=(4,)).model_copy(
        update={"joined": (Member(change="x", groups=(2,)),)}
    )

    mapping = story_mapping(joined, {"y": "feature-y", "x": "feature-x"})

    assert mapping == StoryMapping(parent="feature-y", related=("feature-x",))


def test_a_unit_of_one_change_relates_nothing() -> None:
    mapping = story_mapping(unit("y/4", change="y", groups=(4,)), {"y": "feature-y"})

    assert mapping == StoryMapping(parent="feature-y", related=())
