"""The lane restacks run in: its own workers, apart from the build pool.

A restack is the part of a unit's flow whose only cause is that its base moved.
It takes no build slot, starts when it is seen, and runs in the order it was
seen, at most `limits.max_concurrent_restacks` at once.
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from types import TracebackType

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.events import Claim
from agent_build_kit.pipeline.unit_store import StoredUnit

Move = Callable[[StoredUnit], None]
Work = Callable[[], None]
Owed = Callable[[list[StoredUnit]], Collection[str]]


def owed_a_restack(
    unit: StoredUnit,
    graph: list[StoredUnit],
    *,
    holds_base: Callable[[StoredUnit], bool],
    held: Callable[[StoredUnit], bool],
    leased: Callable[[StoredUnit], bool],
) -> bool:
    """Whether `unit` is owed a restack: its cause says its base moved, its branch does
    not hold the base, no run holds the branch, no lease names it, and nothing it
    depends on is unmerged."""
    raise NotImplementedError


def owed_units(inst: Installation, units: list[StoredUnit]) -> set[str]:
    """The ids of the units owed a restack, read from the repositories' branches."""
    raise NotImplementedError


class RestackLane:
    """A pool of `cap` workers and a first-seen queue with one entry per unit."""

    def __init__(self, cap: int, *, move: Move, claim: Claim, owed: Owed = lambda units: ()):
        raise NotImplementedError

    def hand_over(
        self, unit: StoredUnit, work: Work | None = None, *, done: Callable[[], None] | None = None
    ) -> None:
        """Queue `unit`'s restack once and start it before returning when a worker is free.

        `work` is what runs under the unit's branch claim (the lane's `move` of the unit
        when none is given); `done` runs after it, or when the unit is dropped."""
        raise NotImplementedError

    def scan(self, units: list[StoredUnit]) -> None:
        """Hand over every unit the lane's `owed` names that is not already queued."""
        raise NotImplementedError

    def drain(self) -> None:
        """Return once nothing is running or waiting."""
        raise NotImplementedError

    @property
    def running(self) -> list[str]:
        raise NotImplementedError

    @property
    def waiting(self) -> list[str]:
        raise NotImplementedError

    def __enter__(self) -> RestackLane:
        raise NotImplementedError

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        raise NotImplementedError
