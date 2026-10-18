"""What a live test does when a scratch tick that built nothing was stopped by usage."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from agent_build_kit.pipeline.pause import PAUSE_MARKER, is_paused
from tests.factories import git

if TYPE_CHECKING:
    from tests.scratch_tick import Scratch


def skip_on_usage_condition(scratch: Scratch, branch: str) -> None:
    """Skip the running test when `branch` is not on the scratch's remote and the scratch's pause
    marker holds an unexpired `usage` or `rate_limit` pause; return otherwise."""
    try:
        git(scratch.remote, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
        return
    except subprocess.CalledProcessError:
        pass
    pause = is_paused(scratch.state / PAUSE_MARKER)
    if pause is None or pause.kind == "network":
        return
    pytest.skip(
        f"{pause.reason}: usage is an environment condition, and the build was not attempted"
    )
