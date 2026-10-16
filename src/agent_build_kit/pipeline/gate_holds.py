"""Evaluating every split's gate and keeping its result in the held set (spec: split-gate-usage)."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import datetime
from typing import Literal

from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.shell import Run


class GateAction(Frozen):
    """What an evaluation did, or would do, to one split's gate entry."""

    split: str
    action: Literal["hold", "renew", "lift"]
    reason: str


def evaluate_gates(
    installation: Installation,
    *,
    now: datetime,
    dry_run: bool = False,
    refresh: bool = False,
    read: Callable[[], object] | None = None,
    run: Run = subprocess.run,
) -> list[GateAction]:
    """Evaluate every split with a gate and write, renew or lift its `gate` entry; with
    `dry_run` only report. The only writer of gate entries."""
    raise NotImplementedError
