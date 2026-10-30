"""The one layer that repeats forge calls, for every host."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from agent_build_kit.forges.base import COMMENT_MARKER, Forge
from agent_build_kit.forges.operations import OPERATIONS, OperationSpec
from agent_build_kit.resilient_base import Clock, ResilientBase, RetryPolicy, delegating

__all__ = ["RETRIES_COUNTER", "Clock", "ResilientForge", "RetryPolicy"]

RETRIES_COUNTER = "abk.forge.retries"


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


class ResilientForge(ResilientBase[Forge]):
    """A forge that applies `OPERATIONS` to every call it delegates to `inner`.

    Anything that is not an operation (`name`, `client`, ...) is the inner
    forge's own."""

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
        super().__init__(inner, policy, clock, sleeper, table=table)

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


for _name in OPERATIONS:
    setattr(ResilientForge, _name, delegating(_name))
