"""The settings the usage estimate reads: a margin, a cap, and an allowance per window."""

import pytest
from pydantic import ValidationError

from agent_build_kit.config import ClaudeLimitsConfig, UsageWindowConfig


def test_the_defaults_are_a_margin_of_five_a_cap_of_three_and_ten_and_two_points() -> None:
    limits = ClaudeLimitsConfig()

    assert limits.usage_headroom_margin_pct == 5
    assert limits.usage_estimate_max_starts == 3
    assert limits.session.usage_unit_allowance_pct == 10
    assert limits.weekly.usage_unit_allowance_pct == 2


@pytest.mark.parametrize("setting", ["usage_headroom_margin_pct", "usage_estimate_max_starts"])
def test_a_negative_margin_or_cap_is_refused(setting: str) -> None:
    with pytest.raises(ValidationError):
        ClaudeLimitsConfig.model_validate({setting: -1})


def test_a_negative_allowance_is_refused() -> None:
    with pytest.raises(ValidationError):
        UsageWindowConfig.model_validate({"usage_unit_allowance_pct": -1})
