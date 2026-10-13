"""Merge the recommended policy into a known agent's configuration, over its descriptor."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from enum import StrEnum
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.runtimes.known_agents import ApplyFormat, ApplyPolicy

BACKUP_SUFFIX = ".abk-backup"

# A writer per format: the text of a configuration with the lists at the given key paths set.
WRITERS: dict[ApplyFormat, Callable[..., str]] = {}


class ApplyRefused(Exception):
    """The configuration cannot be merged into; nothing was written."""


class Status(StrEnum):
    WRITTEN = "written"
    WOULD_WRITE = "would_write"  # a dry run that found something to add
    UNCHANGED = "unchanged"
    ABSENT = "absent"


class ApplyResult(Frozen):
    path: Path
    status: Status
    message: str = ""
    diff: str = ""
    added: tuple[str, ...] = ()
    backup: Path | None = None
    # The toolset's list before and after, when it was asked for and differs.
    toolset_change: tuple[tuple[str, ...], tuple[str, ...]] | None = None


def resolve_home(descriptor: ApplyPolicy, env_file: Path | None = None) -> Path:
    """The agent's home: the descriptor's variable when set, else its default under the home."""
    raise NotImplementedError


def apply(
    descriptor: ApplyPolicy,
    home: Path,
    extra: Iterable[str] = (),
    toolset: bool = False,
    dry_run: bool = False,
) -> ApplyResult:
    """Merge the recommended patterns, then `extra`, into `<home>/<file>`; raises `ApplyRefused`."""
    raise NotImplementedError
