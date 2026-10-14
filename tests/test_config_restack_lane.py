"""`global_limits.max_concurrent_restacks`: how many restacks the lane runs at once."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from agent_build_kit.config import LimitsConfig


def limits(**values: Any) -> Any:
    """The limits as the configuration file gives them, read through the schema."""
    return LimitsConfig.model_validate(values)


def test_two_restacks_run_at_once_by_default() -> None:
    assert limits().max_concurrent_restacks == 2


@pytest.mark.parametrize("cap", [1, 8])
def test_a_positive_whole_number_is_taken(cap: int) -> None:
    assert limits(max_concurrent_restacks=cap).max_concurrent_restacks == cap


@pytest.mark.parametrize("value", [0, -1, 1.5, "two"])
def test_a_cap_that_is_not_a_positive_whole_number_is_refused_by_name(value: object) -> None:
    assert limits(max_concurrent_restacks=1).max_concurrent_restacks == 1

    with pytest.raises(ValidationError, match="max_concurrent_restacks") as refused:
        limits(max_concurrent_restacks=value)

    assert "Extra inputs" not in str(refused.value)
