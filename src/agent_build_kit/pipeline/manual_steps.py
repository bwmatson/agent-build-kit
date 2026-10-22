"""Running the checks of the manual steps units wait on, each tick pass (spec: manual-steps)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen


class ManualAction(Frozen):
    """What an evaluation found for one unmet step."""

    unit: str
    slug: str
    outcome: Literal["met", "unmet", "failed", "timeout"]


def evaluate_manual_steps(
    installation: Installation, *, now: datetime, dry_run: bool = False
) -> list[ManualAction]:
    """Run the check of every unmet step of every waiting unit in the unit's worktree, record
    the result, mark a passing step done and readmit its unit once none is unmet."""
    raise NotImplementedError
