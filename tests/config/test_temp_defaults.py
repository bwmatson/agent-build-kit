"""`global_limits.temp_keep_hours` defaults to 16 hours and `temp_warn_mb` keeps its default (spec:
temp-folder-reporting). The sweep under the default is tested in the sweep's own tests."""

from __future__ import annotations

from agent_build_kit.config import LimitsConfig


def test_the_default_limits_keep_sixteen_hours_and_warn_at_2048_megabytes() -> None:
    limits = LimitsConfig()

    assert limits.temp_keep_hours == 16
    assert limits.temp_warn_mb == 2048
