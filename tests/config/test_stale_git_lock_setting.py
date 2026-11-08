"""`global_limits.stale_git_lock_seconds`: how old an empty lock is before a restack clears it."""

import pytest
from pydantic import ValidationError

from agent_build_kit.config import LimitsConfig


def test_a_stale_lock_is_ten_minutes_old_by_default() -> None:
    assert LimitsConfig().stale_git_lock_seconds == 600


@pytest.mark.parametrize("value", [0, -1])
def test_a_value_that_is_not_above_zero_is_refused(value: int) -> None:
    with pytest.raises(ValidationError, match="greater than 0"):
        LimitsConfig(stale_git_lock_seconds=value)
