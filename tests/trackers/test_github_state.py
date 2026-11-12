"""GitHub issue state: open or closed with a reason, plus status labels the tracker makes when
the repository lacks them."""

from __future__ import annotations

import pytest

from tests.trackers.github_issue_host import IssueHost
from tests.trackers.github_support import tracker_on

pytestmark = pytest.mark.usefixtures("github_env")

ACTIVE = "status:active"
IN_REVIEW = "status:in-review"
BLOCKED = "status:blocked"
STATUS = {ACTIVE, IN_REVIEW, BLOCKED}


def group_on(host: IssueHost) -> str:
    return host.seed("Group", type="Story")


def test_a_group_item_set_active_in_review_blocked_and_done_leaves_the_expected_labels() -> None:
    host = IssueHost()
    group = group_on(host)
    host.repo_labels.update(STATUS)
    tracker = tracker_on(host)

    tracker.update(group, {"state": "active"})
    assert (host.issues[int(group)]["state"], host.labels_of(group) & STATUS) == ("open", {ACTIVE})

    tracker.set_tag(group, "in-review", True)
    assert host.labels_of(group) & STATUS == {ACTIVE, IN_REVIEW}
    assert host.issues[int(group)]["state"] == "open"

    tracker.set_tag(group, "blocked", True)
    assert host.labels_of(group) & STATUS == {ACTIVE, IN_REVIEW, BLOCKED}

    done = tracker.update(group, {"state": "done"})
    assert host.issues[int(group)]["state"] == "closed"
    assert host.issues[int(group)]["state_reason"] == "completed"
    assert done.state == "closed"


def test_a_tag_is_taken_off_and_a_persons_label_stays() -> None:
    host = IssueHost()
    group = host.seed("Group", type="Story", labels=("bug", BLOCKED))
    tracker = tracker_on(host)

    tracker.set_tag(group, "blocked", False)

    assert host.labels_of(group) == {"bug"}


def test_a_removed_task_is_closed_as_not_planned() -> None:
    host = IssueHost()
    task = host.seed("Task", type="Task")

    tracker_on(host).update(task, {"state": "removed"})

    assert host.issues[int(task)]["state"] == "closed"
    assert host.issues[int(task)]["state_reason"] == "not_planned"


def test_a_missing_status_label_is_created_and_reported() -> None:
    host = IssueHost()
    group = group_on(host)
    assert ACTIVE not in host.repo_labels
    tracker = tracker_on(host)

    tracker.update(group, {"state": "active"})

    assert host.label_creates == [ACTIVE]
    assert ACTIVE in host.labels_of(group)
    assert tracker.created_labels == (ACTIVE,)


def test_a_status_label_that_exists_is_not_created_again() -> None:
    host = IssueHost()
    first, second = group_on(host), group_on(host)
    tracker = tracker_on(host)

    tracker.update(first, {"state": "active"})
    tracker.update(second, {"state": "active"})

    assert host.label_creates == [ACTIVE]
    assert ACTIVE in host.labels_of(second)
