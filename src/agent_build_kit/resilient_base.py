"""The retry engine the forge and tracker wrappers share."""

from __future__ import annotations

import logging
import random
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from agent_build_kit import telemetry
from agent_build_kit.forges.operations import OperationSpec
from agent_build_kit.forges.transport import (
    MAX_DELAY,
    TRANSIENT,
    HostUnavailable,
    RateLimited,
    TransportError,
)
from agent_build_kit.model import Frozen

log = logging.getLogger(__name__)


class Clock(Protocol):
    def monotonic(self) -> float: ...


class RetryPolicy(Frozen):
    """`attempts` is the most calls one operation makes, the first included;
    `deadline_seconds` bounds the time from the first call to the last wait."""

    attempts: int
    deadline_seconds: float


class ResilientBase[Inner]:
    """Applies a table of operations to every call it delegates to `inner`.

    Anything that is not an operation is the inner object's own. A subclass names
    what its logs and counter call the inner object, and supplies the look-up of a create
    (`_landed`); it may narrow `_can_ask`, whether a failed create can be looked up at all."""

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
        self._inner = inner
        self._policy = policy
        self._clock = clock
        self._sleep = sleeper
        self._table = table

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._inner, name)

    def _invoke(self, name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        spec = self._table[name]
        started = self._clock.monotonic()
        attempt = 0
        # For a create: its transient failure, while the declared read is asked
        # whether it landed.
        unconfirmed: TransportError | None = None
        if spec.kind == "claim":
            # A claim says whether the caller won; repeating it could report a win it did not make.
            return getattr(self._inner, name)(*args, **kwargs)
        while True:
            try:
                if unconfirmed is None:
                    return getattr(self._inner, name)(*args, **kwargs)
                found = self._landed(spec, args, kwargs)
                if found is not None:
                    telemetry.count(self._retries_counter, operation=name, outcome="landed")
                    return found
                failure, unconfirmed = unconfirmed, None
            except TRANSIENT as error:
                failure = error
                attempt += 1
                # A rate-limited call was refused before it did anything.
                if (
                    spec.kind == "create"
                    and unconfirmed is None
                    and not isinstance(error, RateLimited)
                ):
                    if not self._can_ask(spec, args, kwargs):
                        if spec.contains:
                            return self._contained(name, error, attempt)
                        raise
                    unconfirmed = error
                    continue
            if self._pause(name, failure, attempt, started):
                return self._neutral(spec)

    @staticmethod
    def _neutral(spec: OperationSpec) -> Any:
        # A tuple is declared in the table so that no caller shares a list.
        return list(spec.neutral) if isinstance(spec.neutral, tuple) else spec.neutral

    def _contained(self, name: str, failure: TransportError, attempt: int) -> Any:
        log.warning(
            "%s %s: contained after %d attempts (%s)", self._subject, name, attempt, failure
        )
        telemetry.count(self._retries_counter, operation=name, outcome="contained")
        return self._neutral(self._table[name])

    def _can_ask(self, spec: OperationSpec, args: tuple[Any, ...], kwargs: dict[str, Any]) -> bool:
        """Whether a create that failed can be looked up before it is repeated: its table
        entry names a read, and the inner object has it."""
        return spec.lands is not None and callable(getattr(self._inner, spec.lands, None))

    def _landed(self, spec: OperationSpec, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        """What the create made, or None when nothing shows it landed."""
        raise NotImplementedError

    def _pause(self, name: str, failure: TransportError, attempt: int, started: float) -> bool:
        """Wait before the next attempt. When the call is given up instead,
        True for a call declared to be contained, else it raises: the error itself
        when the host asks for longer than the ceiling, else `HostUnavailable`."""
        hint = getattr(failure, "retry_after", None) or 0.0
        wait = max(min(0.5 * 2 ** (attempt - 1) * random.uniform(0.5, 1.5), MAX_DELAY), hint)
        elapsed = self._clock.monotonic() - started
        if (
            hint > MAX_DELAY
            or attempt >= self._policy.attempts
            or elapsed + wait > self._policy.deadline_seconds
        ):
            if self._table[name].contains:
                self._contained(name, failure, attempt)
                return True
            telemetry.count(self._retries_counter, operation=name, outcome="exhausted")
            if hint > MAX_DELAY:
                raise failure
            raise HostUnavailable(name, str(failure), attempt) from failure
        log.info(
            "%s %s: attempt %d of %d failed (%s); waiting %.1fs",
            self._subject,
            name,
            attempt,
            self._policy.attempts,
            failure,
            wait,
        )
        telemetry.count(self._retries_counter, operation=name, outcome="retried")
        self._sleep(wait)
        return False


def delegating(name: str) -> Callable[..., Any]:
    """A method that runs the inner operation `name` through the retry rules."""

    def call(self: ResilientBase[Any], *args: Any, **kwargs: Any) -> Any:
        return self._invoke(name, args, kwargs)

    call.__name__ = name
    return call
