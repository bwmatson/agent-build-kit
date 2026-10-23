"""The outcome and agreement counters are emitted by the source and listed in the catalogue
(spec: review-outcomes, outcomes and agreement are counted)."""

from __future__ import annotations

from agent_build_kit.serve.metrics import catalogue

NAMES = ("abk.review.outcome", "abk.review.agreement")


def test_the_catalogue_lists_the_outcome_counter_by_outcome_tier_and_class_only() -> None:
    listed = {i.name: i for i in catalogue()}

    assert listed["abk.review.outcome"].type == "counter"
    assert set(listed["abk.review.outcome"].attributes) == {"outcome", "tier", "class"}


def test_the_catalogue_lists_the_agreement_counter_by_class_and_acceptance_only() -> None:
    listed = {i.name: i for i in catalogue()}

    assert listed["abk.review.agreement"].type == "counter"
    assert set(listed["abk.review.agreement"].attributes) == {"class", "accepted"}


def test_no_listed_review_counter_carries_a_unit_id() -> None:
    listed = {i.name: i for i in catalogue() if i.name in NAMES}

    assert set(listed) == set(NAMES)
    for instrument in listed.values():
        assert not {"unit", "unit_id", "change"} & set(instrument.attributes)
