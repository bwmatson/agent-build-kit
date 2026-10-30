"""The retry engine the forge and tracker wrappers share."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol

from agent_build_kit.forges.operations import OperationSpec
from agent_build_kit.model import Frozen


class Clock(Protocol):
    def monotonic(self) -> float: ...


class RetryPolicy(Frozen):
    """`attempts` is the most calls one operation makes, the first included;
    `deadline_seconds` bounds the time from the first call to the last wait."""

    attempts: int
    deadline_seconds: float


class ResilientBase[Inner]:
    """Applies a table of operations to every call it delegates to `inner`."""

    _subject = "object"
    _retries_counter = "abk.object.retries"
    _inner: Inner

    def __init__(
        self,
        inner: Inner,
        policy: RetryPolicy,
        clock: Clock,
        sleeper: Callable[[float], None],
        *,
        table: Mapping[str, OperationSpec],
    ) -> None:
        raise NotImplementedError

    def _can_ask(self, spec: OperationSpec, args: tuple[Any, ...], kwargs: dict[str, Any]) -> bool:
        raise NotImplementedError

    def _landed(self, spec: OperationSpec, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        raise NotImplementedError


def delegating(name: str) -> Callable[..., Any]:
    """A method that runs the inner operation `name` through the retry rules."""
    raise NotImplementedError
