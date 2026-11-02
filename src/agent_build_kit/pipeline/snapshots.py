"""What the outside world says, read from a snapshot with its age.

A pull request's state, an account's usage reading and the pause markers are collected
by the round and read by a build step through this module, which returns the value and
how old it is. A step that finds a snapshot too old records a refresh request and the next
round refreshes it; it does not ask the host or the usage endpoint itself.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from agent_build_kit.model import Frozen

if TYPE_CHECKING:
    from agent_build_kit.pipeline.usage_guard import UsageReading

PR = "pr"
USAGE = "usage"
PAUSES = "pauses"

# Told the key of what to refresh (a repo, an account, or None), it returns the new value.
Collector = Callable[[str | None], object]


class Snapshot[T](Frozen):
    """A value and when it was collected; both None when nothing has been collected."""

    value: T | None = None
    collected_at: datetime | None = None
    age: timedelta | None = None


class PullRequestState(Frozen):
    """What a snapshot holds of one pull request."""

    state: str
    mergeable: bool | None = None
    checks: dict[str, str] = {}
    labels: tuple[str, ...] = ()


class Pauses(Frozen):
    """The pause markers: when each paused unit may resume, by unit id."""

    resume_at: dict[str, datetime] = {}


class Request(Frozen):
    """One request for a refresh, by kind and key."""

    kind: str
    key: str | None = None


def pr(state_dir: Path, repo: str, number: int) -> Snapshot[PullRequestState]:
    raise NotImplementedError


def usage(state_dir: Path, account: str | None) -> Snapshot[UsageReading]:
    raise NotImplementedError


def pauses(state_dir: Path) -> Snapshot[Pauses]:
    raise NotImplementedError


def request_refresh(state_dir: Path, kind: str, key: str | None = None) -> None:
    raise NotImplementedError


def requested(state_dir: Path) -> list[Request]:
    raise NotImplementedError


def run_round(
    state_dir: Path, collectors: Mapping[str, Collector], max_age: Mapping[str, timedelta]
) -> None:
    raise NotImplementedError
