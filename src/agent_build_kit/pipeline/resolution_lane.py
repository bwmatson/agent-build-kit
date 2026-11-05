"""The resolution lane: the restack lane under its new name (a stub until the rename lands)."""

from __future__ import annotations

from typing import Any

from agent_build_kit.pipeline.restack_lane import RestackLane


class ResolutionLane(RestackLane):
    """The lane a restack, a moved-base run and a comment rework run in."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError
