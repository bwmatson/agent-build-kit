"""The claim on a GitHub issue is an assignment read back, not a compare-and-swap: the earliest
assignee wins, the kit withdraws when it lost, and an issue with anyone else on it is not the
kit's."""

from __future__ import annotations

import logging

import pytest

from tests.trackers.github_issue_host import SYNC_ACCOUNT, IssueHost
from tests.trackers.github_support import tracker_on

pytestmark = pytest.mark.usefixtures("github_env")

OTHER = "other-person"


def test_an_unassigned_group_item_is_claimed_with_the_sync_account_as_its_only_assignee() -> None:
    host = IssueHost()
    group = host.seed("Group", type="Story")
    tracker = tracker_on(host)

    assert tracker.claim(group) is True

    assert host.assignees_of(group) == [SYNC_ACCOUNT]
    assert tracker.get(group).assignees == (SYNC_ACCOUNT,)


def test_an_earlier_assignee_wins_and_the_kits_assignment_is_removed() -> None:
    host = IssueHost()
    group = host.seed("Group", type="Story")
    host.race(group, OTHER)

    assert tracker_on(host).claim(group) is False

    assert host.assignees_of(group) == [OTHER]


def test_an_issue_with_another_assignee_is_not_the_kits_and_names_them(
    caplog: pytest.LogCaptureFixture,
) -> None:
    host = IssueHost()
    group = host.seed("Group", type="Story", assignees=(SYNC_ACCOUNT, OTHER))

    with caplog.at_level(logging.INFO):
        held = tracker_on(host).claim(group)

    assert held is False
    assert host.assignees_of(group) == [SYNC_ACCOUNT, OTHER]
    assert OTHER in caplog.text


def test_a_group_item_the_sync_account_already_holds_alone_is_held() -> None:
    host = IssueHost()
    group = host.seed("Group", type="Story", assignees=(SYNC_ACCOUNT,))

    assert tracker_on(host).claim(group) is True

    assert host.assignees_of(group) == [SYNC_ACCOUNT]


def test_an_earlier_assignee_who_was_since_unassigned_does_not_win() -> None:
    host = IssueHost()
    group = host.seed("Group", type="Story", assignees=(OTHER,))
    host.unassign(group, OTHER)

    assert tracker_on(host).claim(group) is True

    assert host.assignees_of(group) == [SYNC_ACCOUNT]


def test_a_claim_held_alone_after_an_earlier_assignee_left_is_not_released() -> None:
    host = IssueHost()
    group = host.seed("Group", type="Story", assignees=(OTHER, SYNC_ACCOUNT))
    host.unassign(group, OTHER)

    assert tracker_on(host).claim(group) is True

    assert host.assignees_of(group) == [SYNC_ACCOUNT]


def test_the_identity_is_the_account_the_token_belongs_to() -> None:
    assert tracker_on(IssueHost()).identity().name == SYNC_ACCOUNT


def test_the_capabilities_report_no_revision_check() -> None:
    assert tracker_on(IssueHost()).capabilities().revision_check is False


def test_an_update_with_a_stale_revision_is_not_refused() -> None:
    host = IssueHost()
    group = host.seed("Group", type="Story")

    done = tracker_on(host).update(group, {"state": "active"}, "stale-revision")

    assert done.state == "open"
