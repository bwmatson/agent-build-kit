"""What a split moves, what stays, and what is mixed, read from the source's working tree."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from enum import StrEnum

from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen


class SplitUsageError(ValueError):
    """The selection names something the source does not have, or a value that is no side."""


class RefusalKind(StrEnum):
    MIXED = "mixed"
    DESTINATION_LACKS_REPO = "destination-lacks-repo"
    SPANNING_UNIT = "spanning-unit"
    IN_FLIGHT_UNIT = "in-flight-unit"


class Refusal(Frozen):
    kind: RefusalKind
    line: str


class GroupSide(Frozen):
    """One group of a change: its number and the repo and project its heading tags."""

    number: int
    repo: str
    project: str


class MixedChange(Frozen):
    name: str
    groups: tuple[GroupSide, ...]


class Unreadable(Frozen):
    """A `tasks.md` that failed to read: the change or archive entry, the line and the message."""

    name: str
    line: int
    message: str


class SplitPlan(Frozen):
    repo: str
    project: str | None = None
    changes_moved: tuple[str, ...] = ()
    changes_staying: tuple[str, ...] = ()
    changes_mixed: tuple[MixedChange, ...] = ()
    changes_unreadable: tuple[Unreadable, ...] = ()
    archive_moved: tuple[str, ...] = ()
    archive_staying: tuple[str, ...] = ()
    archive_mixed: tuple[MixedChange, ...] = ()
    archive_unclassified: tuple[str, ...] = ()
    archive_unreadable: tuple[Unreadable, ...] = ()
    specs_moved: tuple[str, ...] = ()
    specs_shared: tuple[str, ...] = ()
    specs_unowned: tuple[str, ...] = ()
    units_moved: tuple[str, ...] = ()
    units_blocking: tuple[str, ...] = ()
    # `M path`, `?? path` and `D path` lines; None when the source is not under git.
    uncommitted: tuple[str, ...] | None = None
    refusals: tuple[Refusal, ...] = ()


def plan_split(
    source: Installation,
    repo: str,
    project: str | None = None,
    allow_mixed: str | None = None,
    specs: Sequence[str] = (),
    *,
    destination_repos: Collection[str] | None = None,
) -> SplitPlan:
    raise NotImplementedError


def uncommitted(source: Installation) -> tuple[str, ...] | None:
    raise NotImplementedError
