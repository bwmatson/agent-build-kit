"""Changes since a cursor on GitHub issues: pull requests are left out, a cursor neither skips nor
repeats issues updated in the same second, an unchanged page is not read again, and an issue a
person made is returned flagged foreign."""

from __future__ import annotations

import pytest

from tests.trackers.github_issue_host import IssueHost
from tests.trackers.github_support import tracker_on

pytestmark = pytest.mark.usefixtures("github_env")

INSTANT = "2026-10-20T09:14:02Z"
LATER = "2026-10-20T09:15:00Z"


def at(second: int) -> str:
    return f"2026-10-20T09:{second // 60:02d}:{second % 60:02d}Z"


def test_pull_requests_are_not_returned() -> None:
    host = IssueHost()
    group = host.seed("Group", type="Story", updated_at=at(1))
    host.seed_pull_request("A pull request", "Part of #1")

    changes, _ = tracker_on(host).changed_since(None)

    assert [change.item_id for change in changes] == [group]


def test_more_changes_than_one_page_are_all_returned_once_in_order() -> None:
    host = IssueHost()
    ids = [host.seed(f"Item {n}", type="Story", updated_at=at(n)) for n in range(105, 0, -1)]

    changes, _ = tracker_on(host).changed_since(None)

    assert [change.item_id for change in changes] == list(reversed(ids))


def test_the_third_issue_updated_in_the_same_second_is_returned_after_two_were_handled() -> None:
    host = IssueHost()
    tracker = tracker_on(host)
    first = host.seed("First", type="Story", updated_at=INSTANT)
    second = host.seed("Second", type="Story", updated_at=INSTANT)
    handled, cursor = tracker.changed_since(None)
    third = host.seed("Third", type="Story", updated_at=INSTANT)

    changes, _ = tracker.changed_since(cursor)

    assert sorted(change.item_id for change in handled) == sorted([first, second])
    assert [change.item_id for change in changes] == [third]


def test_a_cursor_that_has_seen_everything_returns_nothing() -> None:
    host = IssueHost()
    tracker = tracker_on(host)
    host.seed("First", type="Story", updated_at=INSTANT)
    host.seed("Second", type="Story", updated_at=at(30))
    _, cursor = tracker.changed_since(None)

    changes, again = tracker.changed_since(cursor)

    assert changes == ()
    assert tracker.changed_since(again)[0] == ()


def test_an_issue_updated_again_after_the_cursor_is_returned_again() -> None:
    host = IssueHost()
    tracker = tracker_on(host)
    group = host.seed("Group", type="Story", updated_at=INSTANT)
    _, cursor = tracker.changed_since(None)
    tracker.update(group, {"title": "Renamed"})

    changes, _ = tracker.changed_since(cursor)

    assert [change.item_id for change in changes] == [group]


def test_an_unchanged_page_answered_not_modified_transfers_no_issue_bodies() -> None:
    host = IssueHost()
    tracker = tracker_on(host)
    host.seed("First", type="Story", updated_at=INSTANT)
    host.seed("Second", type="Story", updated_at=at(30))
    _, cursor = tracker.changed_since(None)
    tracker.changed_since(cursor)
    sent = host.bodies_sent

    changes, _ = tracker.changed_since(cursor)

    assert host.not_modified == 1
    assert host.bodies_sent == sent
    assert changes == ()


def test_a_page_that_changed_is_read_again_after_a_not_modified_answer() -> None:
    host = IssueHost()
    tracker = tracker_on(host)
    host.seed("First", type="Story", updated_at=INSTANT)
    _, cursor = tracker.changed_since(None)
    tracker.changed_since(cursor)
    tracker.changed_since(cursor)
    later = host.seed("Later", type="Story", updated_at=LATER)

    changes, _ = tracker.changed_since(cursor)

    assert [change.item_id for change in changes] == [later]


def test_an_issue_a_person_made_is_returned_flagged_foreign() -> None:
    host = IssueHost()
    tracker = tracker_on(host)
    ours = tracker.create("change", "Ours", markers=("feature",))
    theirs = host.seed("Theirs", type="Feature", author="person")

    changes, _ = tracker.changed_since(None)

    assert {change.item_id: change.foreign for change in changes} == {ours.id: False, theirs: True}
