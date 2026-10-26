"""The one layer that repeats tracker calls, for every tracker."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from agent_build_kit.forges.operations import OperationSpec
from agent_build_kit.forges.resilient import Clock, RetryPolicy
from agent_build_kit.trackers.base import Tracker
from agent_build_kit.trackers.operations import OPERATIONS


class ResilientTracker:
    """A tracker that applies `OPERATIONS` to every call it delegates to `inner`."""

    def __init__(
        self,
        inner: Tracker,
        policy: RetryPolicy,
        clock: Clock,
        sleeper: Callable[[float], None],
        *,
        table: Mapping[str, OperationSpec] = OPERATIONS,
    ) -> None:
        raise NotImplementedError

    def __getattr__(self, name: str) -> Any:
        raise NotImplementedError
