"""`global_limits.max_concurrent_unit_tests` limits the whole-suite unit-test runs that execute at
once: a whole number of at least 1, or `null` for no limit (spec: unit-test-concurrency)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_build_kit.config import LimitsConfig


def test_it_defaults_to_no_limit() -> None:
    assert LimitsConfig().max_concurrent_unit_tests is None


@pytest.mark.parametrize("value", [1, 2, 4])
def test_a_whole_number_of_at_least_one_is_accepted(value: int) -> None:
    assert LimitsConfig(max_concurrent_unit_tests=value).max_concurrent_unit_tests == value


def test_null_is_accepted_as_no_limit() -> None:
    limits = LimitsConfig.model_validate({"max_concurrent_unit_tests": None})

    assert limits.max_concurrent_unit_tests is None


@pytest.mark.parametrize("value", [0, -1])
def test_a_value_below_one_is_refused_naming_the_setting(value: int) -> None:
    with pytest.raises(ValidationError, match="max_concurrent_unit_tests"):
        LimitsConfig(max_concurrent_unit_tests=value)
