"""The one layer that repeats forge calls, for every host."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol

from agent_build_kit.forges.base import Forge
from agent_build_kit.forges.operations import OPERATIONS, OperationSpec
from agent_build_kit.model import Frozen


class Clock(Protocol):
    def monotonic(self) -> float: ...


class RetryPolicy(Frozen):
    """`attempts` is the most calls one operation makes, the first included;
    `deadline_seconds` bounds the time from the first call to the last wait."""

    attempts: int
    deadline_seconds: float


class ResilientForge:
    """A forge that applies `OPERATIONS` to every call it delegates to `inner`."""

    def __init__(
        self,
        inner: Forge,
        policy: RetryPolicy,
        clock: Clock,
        sleeper: Callable[[float], None],
        *,
        table: Mapping[str, OperationSpec] = OPERATIONS,
    ) -> None:
        raise NotImplementedError

    def __getattr__(self, name: str) -> Any:
        raise NotImplementedError
