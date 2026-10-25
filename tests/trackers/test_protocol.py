"""The tracker protocol: item shape, children, markers, operation kinds and capabilities."""

from __future__ import annotations

import inspect

from agent_build_kit.trackers.base import Capabilities, Tracker
from agent_build_kit.trackers.local import LocalTracker
from agent_build_kit.trackers.operations import OPERATIONS


def protocol_methods() -> list[str]:
    return sorted(
        name
        for name, member in vars(Tracker).items()
        if inspect.isfunction(member) and not name.startswith("_")
    )


def test_a_story_has_the_same_shape_as_every_other_item() -> None:
    tracker = LocalTracker()
    feature = tracker.create("feature", "Feature")

    story = tracker.get(tracker.create("story", "Story", "the body", feature.id).id)

    assert isinstance(story.id, str) and story.id
    assert story.kind == "story"
    assert (story.title, story.body) == ("Story", "the body")
    assert story.state
    assert story.assignees == ()
    assert story.parent_id == feature.id
    assert story.revision
    assert story.url


def test_every_kind_is_read_back_with_its_own_kind() -> None:
    tracker = LocalTracker()
    feature = tracker.create("feature", "F")
    story = tracker.create("story", "S", parent=feature.id)
    task = tracker.create("task", "T", parent=story.id)

    kinds = [tracker.get(item.id).kind for item in (feature, story, task)]

    assert kinds == ["feature", "story", "task"]
    assert tracker.get(feature.id).parent_id is None


def test_the_children_of_a_feature_and_of_a_story_are_what_was_created_under_them() -> None:
    tracker = LocalTracker()
    feature = tracker.create("feature", "F")
    stories = [tracker.create("story", f"S{n}", parent=feature.id) for n in range(2)]
    tasks = [tracker.create("task", f"T{n}", parent=stories[0].id) for n in range(3)]

    under_feature = tracker.children(feature.id)
    under_story = tracker.children(stories[0].id)

    assert sorted((item.id, item.kind) for item in under_feature) == sorted(
        (item.id, "story") for item in stories
    )
    assert sorted((item.id, item.kind) for item in under_story) == sorted(
        (item.id, "task") for item in tasks
    )
    assert list(tracker.children(stories[1].id)) == []


def test_an_item_created_with_a_marker_is_found_after_a_create_whose_answer_was_lost() -> None:
    tracker = LocalTracker()
    feature = tracker.create("feature", "F")

    tracker.create("story", "S", parent=feature.id, markers=("abk:story-1",))  # answer dropped
    found = tracker.find_by_marker("abk:story-1")

    assert found is not None
    assert found.title == "S"
    assert "abk:story-1" in found.markers
    assert [item.id for item in tracker.children(feature.id)] == [found.id]
    assert tracker.find_by_marker("abk:other") is None


def test_every_protocol_method_has_a_declared_kind() -> None:
    assert protocol_methods()
    assert sorted(set(protocol_methods()) - set(OPERATIONS)) == []


def test_no_kind_names_a_method_the_protocol_lacks() -> None:
    assert OPERATIONS
    assert sorted(set(OPERATIONS) - set(protocol_methods())) == []


def test_a_claim_has_its_own_kind_and_a_create_is_checked_by_marker() -> None:
    assert OPERATIONS["claim"].kind == "claim"
    assert OPERATIONS["create"].kind == "create"
    assert OPERATIONS["create"].lands == "find_by_marker"
    assert OPERATIONS["get"].kind == "read"
    assert OPERATIONS["update"].kind == "idempotent_write"


def test_capabilities_can_be_read_and_differ_between_configurations() -> None:
    full = LocalTracker(Capabilities(revision_check=True, typed=True))
    bare = LocalTracker(Capabilities(revision_check=False, typed=False, hierarchy="label"))

    assert full.capabilities().revision_check is True
    assert full.capabilities().typed is True
    assert bare.capabilities().revision_check is False
    assert bare.capabilities().typed is False
    assert full.capabilities() != bare.capabilities()
