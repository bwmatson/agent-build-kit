"""The one layer that repeats forge calls, for every host."""

from __future__ import annotations

import logging
import random
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from agent_build_kit import telemetry
from agent_build_kit.forges.base import COMMENT_MARKER, Forge
from agent_build_kit.forges.operations import OPERATIONS, OperationSpec
from agent_build_kit.forges.transport import (
    MAX_DELAY,
    TRANSIENT,
    HostUnavailable,
    RateLimited,
    TransportError,
)
from agent_build_kit.model import Frozen

log = logging.getLogger(__name__)

RETRIES_COUNTER = "abk.forge.retries"


class Clock(Protocol):
    def monotonic(self) -> float: ...


class RetryPolicy(Frozen):
    """`attempts` is the most calls one operation makes, the first included;
    `deadline_seconds` bounds the time from the first call to the last wait."""

    attempts: int
    deadline_seconds: float


def _landing_call(
    lands: str, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """The arguments of the read `lands`, for the create that was made with these."""
    repo = args[0]
    # The credential the create used is the one the read is made with.
    run = {"run": kwargs["run"]} if "run" in kwargs else {}
    if lands == "find_pr":
        return (repo,), {"head": kwargs["head"], **run}
    if lands == "stack_of":
        pulls = kwargs["pulls"] if "pulls" in kwargs else args[-1]
        # The PR the create adds is last in both: the bottom one may already
        # be in a closed stack that says nothing about this create.
        return (repo, pulls[-1]), run
    if lands == "merge_commit":
        return (repo, args[1]), run
    # A post or a reply: the comment is found by the pipeline's marker and its body.
    reply = {"reply_to": kwargs["note_id"]} if "note_id" in kwargs else {}
    return (repo, args[1], COMMENT_MARKER, kwargs["body"]), {**reply, **run}


class ResilientForge:
    """A forge that applies `OPERATIONS` to every call it delegates to `inner`.

    Anything that is not an operation (`name`, `client`, ...) is the inner
    forge's own."""

    # What the logs and the retry counter call the host this wraps.
    _subject = "forge"
    _retries_counter = RETRIES_COUNTER

    def __init__(
        self,
        inner: Forge,
        policy: RetryPolicy,
        clock: Clock,
        sleeper: Callable[[float], None],
        *,
        table: Mapping[str, OperationSpec] = OPERATIONS,
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
        return spec.lands is not None and callable(getattr(self._inner, spec.lands, None))

    def _landed(self, spec: OperationSpec, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        assert spec.lands is not None
        read_args, read_kwargs = _landing_call(spec.lands, args, kwargs)
        found = getattr(self._inner, spec.lands)(*read_args, **read_kwargs)
        # A closed stack cannot be what this create made.
        if spec.lands == "stack_of" and found is not None and not found.open:
            return None
        # A post or reply promises a list of ids; the read finds the one comment.
        if spec.lands == "comment_exists" and found is not None:
            return [found]
        return found

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

    def call(self: ResilientForge, *args: Any, **kwargs: Any) -> Any:
        return self._invoke(name, args, kwargs)

    call.__name__ = name
    return call


for _name in OPERATIONS:
    setattr(ResilientForge, _name, delegating(_name))
