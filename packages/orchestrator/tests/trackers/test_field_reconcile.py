"""The three-way reconcile of a field against the last-synced snapshot."""

from __future__ import annotations

from agent_build_kit.trackers.field_reconcile import reconcile_field


def test_only_the_tracker_changed_takes_the_trackers_value() -> None:
    outcome = reconcile_field("title", base="Old", spec="Old", tracker="New")

    assert (outcome.action, outcome.value, outcome.conflict) == ("tracker", "New", None)


def test_only_the_spec_changed_leaves_it_for_the_outbound_pass() -> None:
    outcome = reconcile_field("title", base="Old", spec="New", tracker="Old")

    assert (outcome.action, outcome.value, outcome.conflict) == ("outbound", "New", None)


def test_neither_changed_does_nothing() -> None:
    outcome = reconcile_field("body", base="Same", spec="Same", tracker="Same")

    assert (outcome.action, outcome.conflict) == ("none", None)


def test_both_changed_to_the_same_value_is_no_conflict() -> None:
    outcome = reconcile_field("done", base="open", spec="done", tracker="done")

    assert (outcome.action, outcome.conflict) == ("none", None)


def test_both_changed_text_keeps_the_specs_and_records_the_boards_wording() -> None:
    outcome = reconcile_field(
        "body",
        base="Old",
        spec="Spec text",
        tracker="Board text",
        spec_who="kit",
        tracker_who="Sam",
    )

    assert (outcome.action, outcome.value) == ("spec", "Spec text")
    conflict = outcome.conflict
    assert conflict is not None
    assert (conflict.field, conflict.spec_value, conflict.tracker_value) == (
        "body",
        "Spec text",
        "Board text",
    )
    assert (conflict.kept, conflict.spec_who, conflict.tracker_who) == ("spec", "kit", "Sam")


def test_both_changed_title_follows_the_spec() -> None:
    outcome = reconcile_field("title", base="Old", spec="A", tracker="B")

    assert (outcome.action, outcome.value) == ("spec", "A")
    assert outcome.conflict is not None and outcome.conflict.kept == "spec"


def test_both_changed_assignee_keeps_the_persons_and_records_the_kits_claim_as_lost() -> None:
    outcome = reconcile_field(
        "assignee", base="", spec="sync-bot", tracker="Sam", spec_who="kit", tracker_who="Sam"
    )

    assert (outcome.action, outcome.value) == ("tracker", "Sam")
    conflict = outcome.conflict
    assert conflict is not None
    assert (conflict.kept, conflict.spec_value, conflict.tracker_value) == (
        "tracker",
        "sync-bot",
        "Sam",
    )
    assert (conflict.spec_who, conflict.tracker_who) == ("kit", "Sam")


def test_both_changed_the_done_state_differently_follows_the_tracker() -> None:
    outcome = reconcile_field("done", base="open", spec="done", tracker="blocked")

    assert (outcome.action, outcome.value) == ("tracker", "blocked")
    assert outcome.conflict is not None and outcome.conflict.kept == "tracker"


def test_a_tasks_done_state_follows_the_tracker_when_only_it_changed() -> None:
    outcome = reconcile_field("done", base="open", spec="open", tracker="done")

    assert (outcome.action, outcome.value, outcome.conflict) == ("tracker", "done", None)
