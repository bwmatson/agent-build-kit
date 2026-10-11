"""The decision log: why each unit that is not running is waiting, written when it changes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.vocabulary import WaitReason


class Wait(Frozen):
    """A unit's reason for not running, and the units it waits on."""

    reason: WaitReason
    waits_on: tuple[str, ...] = ()


class WaitRecorder:
    """Appends `{at, unit, reason, waits_on, tick}` to the log at `path` only when a
    unit's reason or what it waits on changes."""

    def __init__(self, path: Path, say: Callable[[str], None]) -> None:
        self.path = path
        self.say = say

    def record(self, waits: Mapping[str, Wait], *, tick: str) -> None:
        """Log what changed since the last call; a unit that left `waits` gets a
        closing record, and its wait a span if it is one the build path does not write."""
        raise NotImplementedError
