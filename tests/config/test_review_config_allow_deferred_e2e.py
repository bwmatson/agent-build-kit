"""`review.auto_land.allow_deferred_e2e`: a boolean, false by default, accepted nowhere else
(spec: review-verdict-e2e-state)."""

from __future__ import annotations

import pytest

from tests.config.test_review_config import refusal
from tests.review_config import workspace

KEY = "allow_deferred_e2e"


def test_the_key_loads_false_when_the_policy_does_not_mention_it() -> None:
    assert workspace().review.auto_land.model_dump()[KEY] is False


def test_the_key_loads_true_when_set_under_auto_land() -> None:
    loaded = workspace({"auto_land": {KEY: True}})

    assert loaded.review.auto_land.model_dump()[KEY] is True


def test_the_key_under_review_is_refused_as_unknown() -> None:
    workspace({"auto_land": {KEY: True}})  # the key has a home, and it is not here

    assert KEY in refusal({KEY: True})


def test_the_key_under_a_repos_review_block_is_refused_as_unknown() -> None:
    workspace({"auto_land": {KEY: True}})

    assert KEY in refusal(app={KEY: True})


@pytest.mark.parametrize("value", ["sometimes", [True], {"a": 1}, 3])
def test_a_value_that_is_not_a_boolean_is_refused(value: object) -> None:
    assert KEY in refusal({"auto_land": {KEY: value}})
