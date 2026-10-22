"""The check-and-fix routine the stub loop and the checks loop share.

The nodes call `check_round` and `fix_round` through this module (`check_loop.check_round`), so a
test can stand a recording fake in their place.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from agent_build_kit.graph.state import UnitRun
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import FeedbackSource

if TYPE_CHECKING:
    from agent_build_kit.graph.nodes import BuildPath, Update


class CheckParked(Exception):
    """The check parked the unit instead of passing or failing; `update` is the node's result."""

    def __init__(self, update: Update) -> None:
        super().__init__("parked")
        self.update = update


class CheckLoop(Frozen):
    """What differs between the two loops: the check, where a failure is saved, the counter,
    the fix prompt and the commit rule (`None`: no commit; else a template over `title` and
    `n`, as `fix: {title} (checks, round {n})`)."""

    check: Callable[[], tuple[bool, str]]
    source: FeedbackSource
    heading: str
    rounds: str
    commit: str | None
    prompt: Callable[[str], str]


def check_round(nodes: BuildPath, state: UnitRun, loop: CheckLoop) -> Update:
    raise NotImplementedError


def fix_round(nodes: BuildPath, state: UnitRun, loop: CheckLoop) -> Update:
    raise NotImplementedError
