"""Conditional updates and claims on the stand-in: what a stale revision does, and what a claim
reports with revision checks on and off."""

from __future__ import annotations

import pytest

from agent_build_kit.trackers.base import Capabilities, StaleRevision
from agent_build_kit.trackers.local import LocalTracker

OTHER = "someone-else"


@pytest.fixture
def checked() -> LocalTracker:
    return LocalTracker(Capabilities(revision_check=True))


@pytest.fixture
def unchecked() -> LocalTracker:
    return LocalTracker(Capabilities(revision_check=False))


@pytest.fixture(params=[True, False], ids=["checked", "unchecked"])
def tracker(request: pytest.FixtureRequest) -> LocalTracker:
    return LocalTracker(Capabilities(revision_check=request.param))


def test_a_stale_revision_is_refused_and_changes_nothing(checked: LocalTracker) -> None:
    story = checked.create("group", "Story")
    read_at = story.revision
    checked.as_identity(OTHER).update(story.id, {"title": "Theirs"})
    left_by_other = checked.get(story.id)
    _, cursor = checked.changed_since(None)

    with pytest.raises(StaleRevision):
        checked.update(story.id, {"title": "Mine"}, expected_revision=read_at)

    assert checked.get(story.id) == left_by_other
    assert left_by_other.title == "Theirs"
    assert checked.changed_since(cursor)[0] == []


def test_a_stale_assignment_is_refused_and_changes_nothing(checked: LocalTracker) -> None:
    story = checked.create("group", "Story")
    checked.as_identity(OTHER).update(story.id, {"body": "edited"})
    left_by_other = checked.get(story.id)

    with pytest.raises(StaleRevision):
        checked.set_assignee(story.id, "me", expected_revision=story.revision)

    assert checked.get(story.id) == left_by_other


def test_the_current_revision_is_accepted_and_moves_the_revision_on(
    checked: LocalTracker,
) -> None:
    story = checked.create("group", "Story")
    checked.as_identity(OTHER).update(story.id, {"body": "edited"})
    current = checked.get(story.id)

    updated = checked.update(story.id, {"title": "Mine"}, expected_revision=current.revision)

    assert updated.title == "Mine"
    assert updated.revision != current.revision


def test_without_revision_checks_a_stale_update_is_applied(unchecked: LocalTracker) -> None:
    story = unchecked.create("group", "Story")
    unchecked.as_identity(OTHER).update(story.id, {"title": "Theirs"})

    updated = unchecked.update(story.id, {"title": "Mine"}, expected_revision=story.revision)

    assert updated.title == "Mine"
    assert unchecked.get(story.id).title == "Mine"


def test_a_claim_on_an_unassigned_story_is_held(tracker: LocalTracker) -> None:
    story = tracker.create("group", "Story")

    assert tracker.claim(story.id) is True

    assert tracker.get(story.id).assignees == (tracker.identity().name,)
    assert tracker.as_identity(OTHER).get(story.id).assignees == (tracker.identity().name,)


def test_a_claim_on_a_story_assigned_to_someone_else_is_not_held(tracker: LocalTracker) -> None:
    story = tracker.create("group", "Story")
    tracker.as_identity(OTHER).claim(story.id)
    assigned = tracker.get(story.id)

    assert tracker.claim(story.id) is False

    assert tracker.get(story.id) == assigned
    assert assigned.assignees == (OTHER,)


def test_without_revision_checks_a_claim_reads_back_and_reports_what_it_finds(
    unchecked: LocalTracker,
) -> None:
    """The stand-in is single-threaded and cannot interleave a competing write inside a claim,
    so this pins only the reported result; the read-back itself belongs to the contract suite."""
    story = unchecked.create("group", "Story")
    assert unchecked.claim(story.id) is True

    # Nothing stops the other identity from writing over it: the next claim says so.
    unchecked.as_identity(OTHER).set_assignee(story.id, OTHER, expected_revision=story.revision)

    assert unchecked.claim(story.id) is False
    assert unchecked.get(story.id).assignees == (OTHER,)


def test_with_revision_checks_the_other_identity_cannot_write_over_a_claim_it_has_not_read(
    checked: LocalTracker,
) -> None:
    story = checked.create("group", "Story")
    assert checked.claim(story.id) is True

    with pytest.raises(StaleRevision):
        checked.as_identity(OTHER).set_assignee(story.id, OTHER, expected_revision=story.revision)

    assert checked.get(story.id).assignees == (checked.identity().name,)
