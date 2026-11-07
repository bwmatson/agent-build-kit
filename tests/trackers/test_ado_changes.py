"""Changes since a cursor on Azure DevOps work items: every change in the area path is listed
once and in order across the host's pages, a cursor neither skips nor repeats an item changed
at the same instant, and an item a person made is returned flagged foreign."""

from __future__ import annotations

import pytest

from tests.trackers.ado_support import AREA_PATH, tracker_on
from tests.trackers.ado_work_item_host import WorkItemHost

pytestmark = pytest.mark.usefixtures("rest_env")

INSTANT = "2026-10-20T09:14:02.903Z"
OTHER_AREA = "Some Project\\Team B"


def at(second: int) -> str:
    return f"2026-10-20T09:14:{second:02d}.000Z"


def test_more_changes_than_one_page_are_all_returned_once_in_order() -> None:
    host = WorkItemHost(page_size=2)
    tracker = tracker_on(host)
    ids = [host.seed("Issue", f"Item {n}", changed=at(n)) for n in (5, 1, 4, 2, 3)]

    changes, _ = tracker.changed_since(None)

    assert [c.item_id for c in changes] == [ids[1], ids[3], ids[4], ids[2], ids[0]]


def test_items_changed_at_the_same_instant_across_a_page_are_returned_once() -> None:
    host = WorkItemHost(page_size=2)
    tracker = tracker_on(host)
    ids = [host.seed("Issue", f"Item {n}", changed=INSTANT) for n in range(5)]

    changes, _ = tracker.changed_since(None)

    assert sorted(c.item_id for c in changes) == sorted(ids)
    assert len(changes) == len(ids)


def test_the_third_item_changed_at_the_same_instant_is_returned_after_two_were_handled() -> None:
    host = WorkItemHost()
    tracker = tracker_on(host)
    first = host.seed("Issue", "First", changed=INSTANT)
    second = host.seed("Issue", "Second", changed=INSTANT)
    handled, cursor = tracker.changed_since(None)
    third = host.seed("Issue", "Third", changed=INSTANT)

    changes, _ = tracker.changed_since(cursor)

    assert sorted(c.item_id for c in handled) == sorted([first, second])
    assert [c.item_id for c in changes] == [third]


def test_a_cursor_that_has_seen_everything_returns_nothing() -> None:
    host = WorkItemHost()
    tracker = tracker_on(host)
    host.seed("Issue", "First", changed=INSTANT)
    host.seed("Issue", "Second", changed=at(30))
    _, cursor = tracker.changed_since(None)

    changes, again = tracker.changed_since(cursor)

    assert changes == ()
    assert tracker.changed_since(again)[0] == ()


def test_an_item_changed_again_after_the_cursor_is_returned_with_its_new_revision() -> None:
    host = WorkItemHost()
    tracker = tracker_on(host)
    item = host.seed("Issue", "First", changed=INSTANT)
    _, cursor = tracker.changed_since(None)
    host.edit(item, title="Renamed")
    host.changed_at(item, at(40))

    changes, _ = tracker.changed_since(cursor)

    assert [(c.item_id, c.revision) for c in changes] == [(item, "3")]


def test_an_item_a_person_made_is_returned_flagged_foreign() -> None:
    host = WorkItemHost()
    tracker = tracker_on(host)
    ours = tracker.create("change", "Ours", markers=("feature",))
    host.changed_at(ours.id, at(1))
    theirs = host.seed("Issue", "Theirs", assigned_to="person@example.com", changed=at(2))

    changes, _ = tracker.changed_since(None)

    assert [(c.item_id, c.foreign) for c in changes] == [(ours.id, False), (theirs, True)]


def test_an_item_outside_the_area_path_is_not_returned() -> None:
    host = WorkItemHost()
    tracker = tracker_on(host)
    inside = host.seed("Issue", "Inside", area_path=AREA_PATH, changed=at(1))
    host.seed("Issue", "Outside", area_path=OTHER_AREA, changed=at(2))

    changes, _ = tracker.changed_since(None)

    assert [c.item_id for c in changes] == [inside]
