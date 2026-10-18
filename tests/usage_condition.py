"""What a live test does when a scratch tick that built nothing was stopped by usage."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from agent_build_kit.pipeline.pause import PAUSE_MARKER, PauseKind, is_paused

if TYPE_CHECKING:
    from tests.scratch_tick import Scratch

FAR_FUTURE = datetime(2099, 1, 1, tzinfo=UTC)


def write_pause(state: Path, reason: str, *, kind: PauseKind, until: datetime = FAR_FUTURE) -> None:
    """A pause marker in `state`, as the pipeline writes one."""
    (state / PAUSE_MARKER).write_text(
        json.dumps({"until": until.isoformat(), "reason": reason, "kind": kind})
    )


def skip_on_usage_condition(scratch: Scratch, branch: str) -> None:
    """Skip the running test when `branch` is not on the scratch's remote and the scratch's pause
    marker holds an unexpired `usage` or `rate_limit` pause; return otherwise."""
    from tests.scratch_tick import branch_on_remote  # noqa: PLC0415 — scratch_tick imports this

    if branch_on_remote(scratch, branch):
        return
    pause = is_paused(scratch.state / PAUSE_MARKER)
    if pause is None or pause.kind == "network":
        return
    pytest.skip(
        f"{pause.reason}: usage is an environment condition, and the build was not attempted"
    )
