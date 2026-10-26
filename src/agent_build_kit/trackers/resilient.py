"""The one layer that repeats tracker calls, for every tracker."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from agent_build_kit.forges.operations import OperationSpec
from agent_build_kit.forges.resilient import Clock, ResilientForge, RetryPolicy, delegating
from agent_build_kit.trackers.base import Tracker
from agent_build_kit.trackers.operations import OPERATIONS


class ResilientTracker(ResilientForge):
    """A tracker that applies `OPERATIONS` to every call it delegates to `inner`, with the
    forge wrapper's backoff and rate-limit rules; a create is looked up by its marker."""

    def __init__(
        self,
        inner: Tracker,
        policy: RetryPolicy,
        clock: Clock,
        sleeper: Callable[[float], None],
        *,
        table: Mapping[str, OperationSpec] = OPERATIONS,
    ) -> None:
        super().__init__(inner, policy, clock, sleeper, table=table)  # type: ignore[arg-type]

    def _landed(self, spec: OperationSpec, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        markers = kwargs.get("markers") or ()
        return getattr(self._inner, str(spec.lands))(markers[0]) if markers else None


for _name in OPERATIONS:
    setattr(ResilientTracker, _name, delegating(_name))
