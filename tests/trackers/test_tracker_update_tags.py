"""`update` carries the kit's status tags on every tracker: only those are replaced, the markers and
a person's tags stay, and a field a tracker cannot write is refused."""

from __future__ import annotations

import pytest

from agent_build_kit.trackers.local import LocalTracker
from tests.trackers.ado_support import tracker_on
from tests.trackers.ado_work_item_host import WorkItemHost


@pytest.mark.usefixtures("rest_env")
def test_azure_replaces_only_the_status_tags_and_reports_the_others() -> None:
    host = WorkItemHost()
    tracker = tracker_on(host)
    made = tracker.create("change", "Change", "", None, markers=("feature",))
    host.edit(made.id, **{"System.Tags": "abk:feature; blocked; mine"})
    current = tracker.get(made.id)

    updated = tracker.update(made.id, {"tags": "in-review"}, current.revision)

    stored = host.items[int(made.id)]["fields"]["System.Tags"]
    assert sorted(t.strip() for t in stored.split(";")) == ["abk:feature", "in-review", "mine"]
    assert updated.tags == ("mine", "in-review")
    assert updated.markers == ("feature",) or updated.markers == ()


@pytest.mark.usefixtures("rest_env")
def test_azure_reports_the_kit_word_of_a_board_state_and_keeps_the_board_word() -> None:
    host = WorkItemHost()
    item = host.seed("Issue", "Change", state="Doing")

    found = tracker_on(host).get(item)

    assert found.state == "Doing"
    assert found.kit_state == "active"


def test_the_stand_in_replaces_only_the_status_tags_too() -> None:
    tracker = LocalTracker()
    item = tracker.create("group", "Group")
    tracker.update(item.id, {"tags": "blocked"})

    updated = tracker.update(item.id, {"tags": "in-review"})

    assert updated.tags == ("in-review",)


def test_the_stand_in_refuses_a_field_no_tracker_writes() -> None:
    tracker = LocalTracker()
    item = tracker.create("group", "Group")

    with pytest.raises(ValueError, match="cannot update"):
        tracker.update(item.id, {"colour": "red"})
