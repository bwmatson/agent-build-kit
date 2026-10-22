"""The review tiers are a label family of their own (spec: review-triage)."""

import re

from agent_build_kit.pipeline.verdict import ReviewTier
from agent_build_kit.pipeline.vocabulary import review_label, review_label_names, state_label_names

HYPHENATED = re.compile(r"^[a-z]+(-[a-z]+)+$")


def test_each_tier_has_a_hyphenated_label_with_a_description_and_a_colour() -> None:
    labels = [review_label(tier) for tier in ReviewTier]

    assert len({label.name for label in labels}) == len(ReviewTier)
    for label in labels:
        assert HYPHENATED.match(label.name), label.name
        assert label.description
        assert re.fullmatch(r"[0-9a-f]{6}", label.color), label.color


def test_the_family_is_the_three_tiers_and_nothing_else() -> None:
    assert review_label_names() == {review_label(tier).name for tier in ReviewTier}


def test_the_review_labels_and_the_state_labels_are_two_families() -> None:
    assert review_label_names()
    assert not review_label_names() & state_label_names()
