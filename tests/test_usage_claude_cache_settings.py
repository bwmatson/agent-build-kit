"""`usage_claude_cache_minutes`: how long a block in Claude Code's own cache is trusted."""

import pytest
from pydantic import ValidationError

from agent_build_kit.config import ClaudeLimitsConfig


def test_unset_it_follows_usage_cache_minutes_and_zero_is_kept() -> None:
    assert ClaudeLimitsConfig().usage_claude_cache_minutes == 15
    assert ClaudeLimitsConfig(usage_cache_minutes=20).usage_claude_cache_minutes == 20

    off = ClaudeLimitsConfig(usage_cache_minutes=20, usage_claude_cache_minutes=0)

    assert off.usage_claude_cache_minutes == 0
    assert ClaudeLimitsConfig(usage_claude_cache_minutes=5).usage_claude_cache_minutes == 5


def test_a_negative_value_is_refused() -> None:
    with pytest.raises(ValidationError):
        ClaudeLimitsConfig(usage_claude_cache_minutes=-1)
