"""A joined unit's Story sits under its own change's Feature and relates the others
(spec: tracker-mapping). The stored `story` field is read, not written (spec: tracker-levels)."""

from __future__ import annotations

from agent_build_kit.pipeline.tracker_file import StoryMapping, story_mapping
from agent_build_kit.pipeline.units import Member
from tests.factories import unit


def test_a_joined_unit_has_its_own_features_story_and_relates_the_others() -> None:
    joined = unit("y/4", change="y", groups=(4,)).model_copy(
        update={"joined": (Member(change="x", groups=(2,)),)}
    )

    mapping = story_mapping(joined, {"y": "feature-y", "x": "feature-x"})

    assert mapping == StoryMapping(parent="feature-y", related=("feature-x",))


def test_a_unit_of_one_change_relates_nothing() -> None:
    mapping = story_mapping(unit("y/4", change="y", groups=(4,)), {"y": "feature-y"})

    assert mapping == StoryMapping(parent="feature-y", related=())
