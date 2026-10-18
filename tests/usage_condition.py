"""What a live test does when a scratch tick that built nothing was stopped by usage."""

from __future__ import annotations

from tests.scratch_tick import Scratch


def skip_on_usage_condition(scratch: Scratch, branch: str) -> None:
    """Skip the running test when `branch` is not on the scratch's remote and the scratch's pause
    marker holds an unexpired `usage` or `rate_limit` pause; return otherwise."""
    raise NotImplementedError
